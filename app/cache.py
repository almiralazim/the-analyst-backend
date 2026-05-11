"""Redis cache client and utilities.

Provides an async Redis connection pool and helper functions for
caching JSON-serializable data with TTL support.
"""

import hashlib
import json
import logging
from typing import Any

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)

# Global Redis connection pool (initialized lazily)
_pool: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Get or create the Redis connection pool."""
    global _pool
    if _pool is None:
        _pool = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _pool


async def close_redis() -> None:
    """Close the Redis connection pool (call on app shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def cache_get(key: str) -> Any | None:
    """Get a cached value by key. Returns None on miss or error."""
    try:
        r = get_redis()
        value = await r.get(key)
        if value is not None:
            return json.loads(value)
    except Exception:
        logger.debug("Cache miss or error for key: %s", key)
    return None


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    """Set a cached value with TTL. Silently fails on error."""
    try:
        r = get_redis()
        await r.set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except Exception:
        logger.debug("Cache set failed for key: %s", key)


async def cache_delete(key: str) -> None:
    """Delete a cached key. Silently fails on error."""
    try:
        r = get_redis()
        await r.delete(key)
    except Exception:
        pass


async def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching a pattern. Use sparingly."""
    try:
        r = get_redis()
        async for key in r.scan_iter(match=pattern):
            await r.delete(key)
    except Exception:
        logger.debug("Cache pattern delete failed: %s", pattern)


def make_cache_key(*parts: str) -> str:
    """Build a namespaced cache key from parts."""
    return ":".join(["analyst"] + list(parts))


def hash_content(content: str) -> str:
    """Create a short hash for cache key generation."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]
