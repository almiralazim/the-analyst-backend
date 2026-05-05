"""Request ID middleware for HTTP request tracing.

Generates a unique request ID per incoming request, propagates it via
contextvars for structured logging, and returns it in response headers.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variables for request tracing, consumed by logging filters.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to each HTTP request.

    For every incoming request:
    - Generates a UUID4 request ID and stores it in ``request_id_var``.
    - Reads the ``X-Correlation-ID`` header (if present) and stores it
      in ``correlation_id_var`` for distributed trace propagation.
    - Adds ``X-Request-ID`` to the response headers.
    - Resets both context variables after the response is sent.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = uuid.uuid4().hex
        rid_token = request_id_var.set(rid)

        cid = request.headers.get("x-correlation-id", "")
        cid_token = correlation_id_var.set(cid)

        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_var.reset(rid_token)
            correlation_id_var.reset(cid_token)
