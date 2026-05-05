"""The Analyst Backend — FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.logging_config import setup_logging
from app.middleware import RequestIdMiddleware
from app.rate_limit import limiter

setup_logging(debug=settings.debug)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info("LLM provider: %s", settings.llm_default_provider)
    logger.info("Storage dir: %s", settings.storage_path)

    # Ensure storage directory exists
    settings.storage_path.mkdir(parents=True, exist_ok=True)

    # Verify Redis connection (non-blocking — app starts even if Redis is down)
    from app.cache import get_redis, close_redis

    try:
        r = get_redis()
        await r.ping()
        logger.info("Redis connected: %s", settings.redis_url)
    except Exception as e:
        logger.warning("Redis unavailable at startup (caching disabled): %s", e)

    yield

    # Shutdown: close Redis pool
    await close_redis()
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
# The Analyst API

A backend service that accepts CSV/Excel uploads, runs a multi-agent analytical pipeline powered by LLMs,
and returns validated findings with confidence scoring. The system learns from corrections and accumulated
knowledge to improve future analyses.

## Core Workflow

1. **Upload** a dataset (CSV/Excel) via `POST /api/v1/datasets`
2. **Ask a question** via `POST /api/v1/pipelines` — agents execute asynchronously
3. **Monitor progress** via WebSocket at `/api/v1/pipelines/{id}/ws` or poll status
4. **Retrieve results** — findings, charts, narrative, and confidence grade from `/api/v1/results/{id}`
5. **Teach the system** — log corrections and learnings via `/api/v1/knowledge/*`

## Authentication

All endpoints (except `/auth/register`, `/auth/login`, `/auth/refresh`, and `/health`) require a
Bearer token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Tokens are obtained from the auth endpoints and expire after 60 minutes. Use the refresh endpoint
to obtain a new access token without re-authenticating.

## Error Format

All errors follow a consistent shape:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description"
  }
}
```

## Rate Limiting

Endpoints are rate-limited per user. When exceeded, a `429` response is returned with a
`Retry-After` header indicating how long to wait before retrying.

## WebSocket

Real-time pipeline progress is available via WebSocket at:
```
ws://<host>/api/v1/pipelines/{pipeline_id}/ws?token=<access_token>
```
""",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {
            "name": "auth",
            "description": "User registration, login, token refresh, and profile retrieval.",
        },
        {
            "name": "datasets",
            "description": "Upload, list, inspect, preview, and delete datasets (CSV/Excel files).",
        },
        {
            "name": "pipelines",
            "description": "Create, monitor, and cancel AI analysis pipelines. Includes WebSocket for real-time progress.",
        },
        {
            "name": "results",
            "description": "Retrieve analysis results: findings, charts, narrative, validation, and export to HTML/PDF/DOCX.",
        },
        {
            "name": "knowledge",
            "description": "Manage corrections and learnings that improve future analyses.",
        },
    ],
)

# Rate limiting
app.state.limiter = limiter


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a 429 response with Retry-After header when rate limit is exceeded."""
    retry_after = exc.detail or "60"
    # Extract the numeric retry window from the exception detail if possible
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMITED",
                "message": f"Rate limit exceeded: {exc.detail}",
            }
        },
        headers={"Retry-After": str(retry_after)},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Request ID middleware for structured logging context propagation
app.add_middleware(RequestIdMiddleware)

# CORS — added last so it runs outermost (handles preflight before other middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Global error handler ---

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}},
    )


# --- Health check endpoints (no auth required) ---

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health/ready")
async def health_ready():
    from sqlalchemy import text as sa_text
    from app.database import engine

    checks = {}
    overall = "ready"

    # PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        checks["postgresql"] = {"status": "ok"}
    except Exception as e:
        checks["postgresql"] = {"status": "error", "error": str(e)}
        overall = "degraded"

    # Redis
    try:
        from app.cache import get_redis as _get_redis
        r = await _get_redis()
        await r.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "error", "error": str(e)}
        # Redis being down is degraded, not fatal
        if overall == "ready":
            overall = "degraded"

    # LLM provider
    checks["llm_provider"] = {
        "status": "ok",
        "provider": settings.llm_default_provider,
    }

    # Storage
    import os
    checks["storage"] = {
        "status": "ok",
        "writable": os.access(str(settings.storage_path), os.W_OK),
    }

    status_code = 200 if overall == "ready" else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# --- Register API routers ---

from app.api.auth import router as auth_router
from app.api.datasets import router as datasets_router
from app.api.pipelines import router as pipelines_router
from app.api.results import router as results_router
from app.api.knowledge import router as knowledge_router

_API_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=_API_PREFIX)
app.include_router(datasets_router, prefix=_API_PREFIX)
app.include_router(pipelines_router, prefix=_API_PREFIX)
app.include_router(results_router, prefix=_API_PREFIX)
app.include_router(knowledge_router, prefix=_API_PREFIX)


# ---------------------------------------------------------------------------
# Patch OpenAPI schema so Swagger UI renders file upload pickers correctly.
# FastAPI 0.115+ generates OpenAPI 3.1 with contentMediaType but Swagger UI
# needs format: binary to show the file chooser widget.
# ---------------------------------------------------------------------------

_original_openapi = app.openapi


def _patched_openapi():
    schema = _original_openapi()
    for schema_name, schema_def in schema.get("components", {}).get("schemas", {}).items():
        for prop_name, prop in schema_def.get("properties", {}).items():
            # Patch array items with contentMediaType to also have format: binary
            items = prop.get("items", {})
            if items.get("contentMediaType") == "application/octet-stream":
                items["format"] = "binary"
            # Patch direct properties with contentMediaType
            if prop.get("contentMediaType") == "application/octet-stream":
                prop["format"] = "binary"
    return schema


app.openapi = _patched_openapi
