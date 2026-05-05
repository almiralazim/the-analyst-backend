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

    yield

    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
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
