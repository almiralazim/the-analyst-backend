"""LLM provider retry logic with exponential backoff and jitter.

Provides a decorator for LLM provider methods that retries on transient
failures (rate limits, server errors, network issues) using exponential
backoff with jitter. Non-retryable errors (client errors, validation
errors) are raised immediately.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import settings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def is_retryable(exc: BaseException) -> bool:
    """Determine whether an exception represents a transient, retryable error.

    Returns True for:
    - HTTP 429 (rate limited) from any provider SDK
    - HTTP 5xx (server errors) from any provider SDK
    - Network connection errors and timeouts
    - Provider-specific transient error types

    Returns False for:
    - HTTP 4xx client errors (except 429)
    - ValueError, TypeError, and other programming errors
    - Authentication/permission errors
    """
    # Generic Python network errors
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True

    # Check for status_code attribute (common across provider SDKs)
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        if status_code == 429:
            return True
        if 500 <= status_code < 600:
            return True
        # Any other HTTP status (4xx except 429) is not retryable
        return False

    # Anthropic SDK exceptions
    try:
        import anthropic

        if isinstance(
            exc,
            (
                anthropic.RateLimitError,
                anthropic.InternalServerError,
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
            ),
        ):
            return True
    except ImportError:
        pass

    # OpenAI SDK exceptions
    try:
        import openai

        if isinstance(
            exc,
            (
                openai.RateLimitError,
                openai.InternalServerError,
                openai.APIConnectionError,
                openai.APITimeoutError,
            ),
        ):
            return True
    except ImportError:
        pass

    # Groq SDK exceptions (follows OpenAI pattern)
    try:
        import groq

        if isinstance(
            exc,
            (
                groq.RateLimitError,
                groq.InternalServerError,
                groq.APIConnectionError,
                groq.APITimeoutError,
            ),
        ):
            return True
    except ImportError:
        pass

    # Google Gemini / API Core exceptions
    try:
        from google.api_core import exceptions as google_exceptions

        if isinstance(
            exc,
            (
                google_exceptions.ResourceExhausted,
                google_exceptions.ServiceUnavailable,
                google_exceptions.InternalServerError,
            ),
        ):
            return True
    except ImportError:
        pass

    return False


def _log_retry(retry_state: RetryCallState) -> None:
    """Log retry attempt with attempt number, wait, and error."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    attempt = retry_state.attempt_number
    error_reason = (
        f"{type(exc).__name__}: {exc}" if exc else "unknown error"
    )

    logger.warning(
        "LLM retry attempt %d, waiting %.1fs. Reason: %s",
        attempt,
        wait,
        error_reason,
    )


def llm_retry() -> Callable[[F], F]:
    """Add retry with exponential backoff + jitter to LLM calls.

    Reads configuration from settings:
    - llm_max_retries: retries (total attempts = 1 + retries)
    - llm_retry_base_seconds: initial backoff wait
    - llm_retry_max_seconds: maximum backoff cap

    Only retries on transient errors (is_retryable).
    Non-retryable errors are raised immediately.
    """
    return retry(
        stop=stop_after_attempt(1 + settings.llm_max_retries),
        wait=wait_exponential_jitter(
            initial=settings.llm_retry_base_seconds,
            max=settings.llm_retry_max_seconds,
            jitter=settings.llm_retry_base_seconds,
        ),
        retry=retry_if_exception(is_retryable),
        before_sleep=_log_retry,
        reraise=True,
    )
