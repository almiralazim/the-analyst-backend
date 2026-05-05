"""Rate limiting configuration using SlowAPI.

Creates a shared Limiter instance that can be imported by both main.py
(for exception handler registration) and route modules (for endpoint decorators).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
)
