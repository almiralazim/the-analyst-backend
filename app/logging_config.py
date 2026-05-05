"""Structured JSON logging configuration.

Provides JSON-formatted log output with request context propagation
and automatic redaction of sensitive data (API keys, tokens, passwords).
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

# Context variables for request tracing — set by RequestIdMiddleware (app/middleware.py)
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

# Patterns that match sensitive values in log output
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[a-zA-Z0-9\-]+"),       # Anthropic API keys
    re.compile(r"sk-[a-zA-Z0-9]+"),              # OpenAI API keys
    re.compile(r"gsk_[a-zA-Z0-9]+"),             # Groq API keys
    re.compile(r'password["\s:=]+[^\s,}"]+'),     # Password values
    re.compile(r'token["\s:=]+[^\s,}"]+'),        # Token values
    re.compile(r'secret["\s:=]+[^\s,}"]+'),       # Secret values
]


class RequestContextFilter(logging.Filter):
    """Inject request_id and correlation_id from contextvars into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("")  # type: ignore[attr-defined]
        record.correlation_id = correlation_id_var.get("")  # type: ignore[attr-defined]
        return True


class SensitiveDataFilter(logging.Filter):
    """Redact API keys, tokens, and passwords from log output."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._redact(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._redact(str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
        return True

    @staticmethod
    def _redact(text: str) -> str:
        """Replace sensitive patterns with [REDACTED]."""
        for pattern in _SENSITIVE_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text


def setup_logging(debug: bool = False) -> None:
    """Configure structured JSON logging for the application.

    Sets up a root logger with JSON output, request context injection,
    and sensitive data redaction. Suppresses noisy third-party loggers.

    Args:
        debug: When True, sets root log level to DEBUG. Otherwise INFO.
    """
    formatter = JsonFormatter(
        fmt="%(timestamp)s %(level)s %(name)s %(message)s",
        timestamp=True,
        rename_fields={"levelname": "level", "name": "logger"},
        defaults={"request_id": "", "correlation_id": ""},
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(RequestContextFilter())
    handler.addFilter(SensitiveDataFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
