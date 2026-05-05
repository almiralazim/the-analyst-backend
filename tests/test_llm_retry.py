"""Tests for LLM retry logic and retryable error classification."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.llm.retry import is_retryable, llm_retry


# --- Helper exception classes for testing ---


class FakeHTTPError(Exception):
    """Exception with a status_code attribute."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(message or f"HTTP {status_code}")


# --- is_retryable tests ---


class TestIsRetryable:
    def test_connection_error_is_retryable(self):
        assert is_retryable(ConnectionError("refused")) is True

    def test_timeout_error_is_retryable(self):
        assert is_retryable(TimeoutError("timed out")) is True

    def test_os_error_is_retryable(self):
        assert is_retryable(OSError("network down")) is True

    def test_http_429_is_retryable(self):
        assert is_retryable(FakeHTTPError(429)) is True

    def test_http_500_is_retryable(self):
        assert is_retryable(FakeHTTPError(500)) is True

    def test_http_502_is_retryable(self):
        assert is_retryable(FakeHTTPError(502)) is True

    def test_http_503_is_retryable(self):
        assert is_retryable(FakeHTTPError(503)) is True

    def test_http_599_is_retryable(self):
        assert is_retryable(FakeHTTPError(599)) is True

    def test_http_400_not_retryable(self):
        assert is_retryable(FakeHTTPError(400)) is False

    def test_http_401_not_retryable(self):
        assert is_retryable(FakeHTTPError(401)) is False

    def test_http_403_not_retryable(self):
        assert is_retryable(FakeHTTPError(403)) is False

    def test_http_404_not_retryable(self):
        assert is_retryable(FakeHTTPError(404)) is False

    def test_http_422_not_retryable(self):
        assert is_retryable(FakeHTTPError(422)) is False

    def test_value_error_not_retryable(self):
        assert is_retryable(ValueError("bad input")) is False

    def test_type_error_not_retryable(self):
        assert is_retryable(TypeError("wrong type")) is False

    def test_runtime_error_not_retryable(self):
        assert is_retryable(RuntimeError("something broke")) is False

    def test_anthropic_rate_limit_error(self):
        anthropic = pytest.importorskip("anthropic")
        httpx = pytest.importorskip("httpx")
        mock_response = httpx.Response(
            status_code=429,
            request=httpx.Request("POST", "https://api.anthropic.com"),
        )
        exc = anthropic.RateLimitError(
            message="rate limited",
            response=mock_response,
            body=None,
        )
        assert is_retryable(exc) is True

    def test_anthropic_internal_server_error(self):
        anthropic = pytest.importorskip("anthropic")
        httpx = pytest.importorskip("httpx")
        mock_response = httpx.Response(
            status_code=500,
            request=httpx.Request("POST", "https://api.anthropic.com"),
        )
        exc = anthropic.InternalServerError(
            message="server error",
            response=mock_response,
            body=None,
        )
        assert is_retryable(exc) is True

    def test_openai_rate_limit_error(self):
        openai = pytest.importorskip("openai")
        httpx = pytest.importorskip("httpx")
        mock_response = httpx.Response(
            status_code=429,
            request=httpx.Request("POST", "https://api.openai.com"),
        )
        exc = openai.RateLimitError(
            message="rate limited",
            response=mock_response,
            body=None,
        )
        assert is_retryable(exc) is True

    def test_openai_internal_server_error(self):
        openai = pytest.importorskip("openai")
        httpx = pytest.importorskip("httpx")
        mock_response = httpx.Response(
            status_code=500,
            request=httpx.Request("POST", "https://api.openai.com"),
        )
        exc = openai.InternalServerError(
            message="server error",
            response=mock_response,
            body=None,
        )
        assert is_retryable(exc) is True


# --- llm_retry decorator tests ---


class TestLlmRetryDecorator:
    @pytest.mark.asyncio
    async def test_succeeds_without_retry(self):
        call_count = 0

        @llm_retry()
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error_then_succeeds(self):
        call_count = 0

        @llm_retry()
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient failure")
            return "recovered"

        result = await fail_then_succeed()
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_immediately_on_non_retryable_error(self):
        call_count = 0

        @llm_retry()
        async def fail_with_client_error():
            nonlocal call_count
            call_count += 1
            raise FakeHTTPError(400, "bad request")

        with pytest.raises(FakeHTTPError):
            await fail_with_client_error()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exhausts_retries_and_raises(self):
        call_count = 0

        @llm_retry()
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("persistent failure")

        with pytest.raises(ConnectionError, match="persistent"):
            await always_fail()
        # 1 initial + 3 retries = 4 total (default config)
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_logs_retry_attempts(self, caplog):
        call_count = 0

        @llm_retry()
        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise TimeoutError("slow")
            return "done"

        with caplog.at_level(logging.WARNING):
            result = await fail_twice()

        assert result == "done"
        assert call_count == 3
        retry_logs = [
            r for r in caplog.records
            if "LLM retry attempt" in r.message
        ]
        assert len(retry_logs) == 2
        assert "TimeoutError" in retry_logs[0].message
