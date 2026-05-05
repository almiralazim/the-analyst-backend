"""Tests for request ID middleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware import RequestIdMiddleware, correlation_id_var, request_id_var


def _build_app() -> FastAPI:
    """Create a minimal FastAPI app with the middleware for testing."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    async def echo():
        return {
            "request_id": request_id_var.get(""),
            "correlation_id": correlation_id_var.get(""),
        }

    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


@pytest.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_request_id_in_response_header(client: AsyncClient):
    """Each response should contain an X-Request-ID header."""
    resp = await client.get("/echo")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) == 32  # uuid4 hex


async def test_request_id_unique_per_request(client: AsyncClient):
    """Consecutive requests should receive distinct request IDs."""
    r1 = await client.get("/echo")
    r2 = await client.get("/echo")
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


async def test_request_id_propagated_to_context(client: AsyncClient):
    """The request ID in the response header should match the contextvar value."""
    resp = await client.get("/echo")
    body = resp.json()
    assert body["request_id"] == resp.headers["x-request-id"]


async def test_correlation_id_from_header(client: AsyncClient):
    """When X-Correlation-ID is sent, it should be available in the contextvar."""
    resp = await client.get("/echo", headers={"X-Correlation-ID": "trace-abc-123"})
    body = resp.json()
    assert body["correlation_id"] == "trace-abc-123"


async def test_correlation_id_empty_when_absent(client: AsyncClient):
    """When no X-Correlation-ID header is sent, the contextvar should be empty."""
    resp = await client.get("/echo")
    body = resp.json()
    assert body["correlation_id"] == ""


async def test_context_vars_reset_after_request(client: AsyncClient):
    """Context vars should be reset after each request completes."""
    await client.get("/echo", headers={"X-Correlation-ID": "first"})
    # After the request, the outer context should have the default values
    assert request_id_var.get("") == ""
    assert correlation_id_var.get("") == ""
