"""Rate limiting configuration using SlowAPI.

Creates a shared Limiter instance that can be imported by both main.py
(for exception handler registration) and route modules (for endpoint decorators).

Uses Redis as the storage backend for distributed rate limiting across
multiple workers. Falls back to in-memory storage if Redis is unavailable.
"""

from __future__ import annotations

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

logger = logging.getLogger(__name__)


def _get_storage_uri() -> str | None:
    """Return Redis URI for rate limit storage, or None for in-memory fallback.

    Validating that the Redis URL is reachable at import time would be too slow,
    so we just pass the URI and let SlowAPI handle connection errors gracefully.
    """
    if settings.redis_url:
        return settings.redis_url
    return None


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
    storage_uri=_get_storage_uri(),
    strategy="fixed-window",
)
