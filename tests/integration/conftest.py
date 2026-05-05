"""Integration test fixtures: async SQLite database, HTTP client, and auth helpers.

Provides a fully isolated test environment using an in-memory SQLite database
with type adapters for PostgreSQL-specific column types (UUID, JSONB).
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import AsyncGenerator

# Set test environment variables before importing any app modules.
# This ensures app/config.py picks up test values instead of production ones.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-only-for-automated-tests-not-production-xxxxxxxx"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["DEBUG"] = "true"
os.environ["STORAGE_DIR"] = "./test_storage"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["LLM_DEFAULT_PROVIDER"] = "anthropic"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB

# ---------------------------------------------------------------------------
# SQLite type adapters for PostgreSQL-specific column types
# ---------------------------------------------------------------------------
# SQLAlchemy models use postgresql.UUID and postgresql.JSONB which SQLite
# doesn't understand natively. These compile-time hooks tell SQLAlchemy how
# to emit DDL for those types when the dialect is SQLite.


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"


@compiles(PG_JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


# ---------------------------------------------------------------------------
# Async SQLite engine and session factory
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite://"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)

TestingSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Pattern to strip PostgreSQL-style casts like  '{}'::jsonb  from DDL.
# SQLite doesn't understand the  ::type  cast syntax.
_PG_CAST_RE = re.compile(r"'([^']*)'::\w+")


@event.listens_for(engine.sync_engine, "connect")
def _register_sqlite_functions(dbapi_conn, connection_record):
    """Register custom SQLite functions and pragmas for test compatibility."""
    # gen_random_uuid() is used as a server_default in several models.
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    # Enable WAL mode and foreign keys.
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
def _strip_pg_casts(conn, cursor, statement, parameters, context, executemany):
    """Rewrite PostgreSQL cast expressions (e.g. '{}'::jsonb) for SQLite.

    SQLite doesn't support the ``::type`` cast syntax. This listener strips
    those casts from DDL statements so that ``CREATE TABLE`` succeeds.
    """
    if _PG_CAST_RE.search(statement):
        statement = _PG_CAST_RE.sub(r"'\1'", statement)
    return statement, parameters


# ---------------------------------------------------------------------------
# Import app modules AFTER environment variables are set
# ---------------------------------------------------------------------------

from app.database import Base, get_db  # noqa: E402
from app.models import (  # noqa: E402, F401
    User,
    Dataset,
    PipelineRun,
    AgentExecution,
    AnalysisResult,
    Correction,
    Learning,
)
from app.rate_limit import limiter  # noqa: E402
from main import app  # noqa: E402

# Disable rate limiting in tests to avoid Redis dependency and cross-test state leakage
limiter.enabled = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="function")
async def db_tables() -> AsyncGenerator[None]:
    """Create all tables before a test and drop them after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def db_session(
    db_tables,
) -> AsyncGenerator[AsyncSession]:
    """Yield an async database session scoped to a single test."""
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(
    db_tables,
) -> AsyncGenerator[AsyncClient]:
    """Async HTTP client wired to the FastAPI app with the test database.

    Overrides the ``get_db`` dependency so all requests use the test
    SQLite database instead of the production PostgreSQL connection.
    """

    async def _override_get_db():
        async with TestingSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def authenticated_user(client: AsyncClient) -> dict:
    """Register a test user and return user info with auth tokens.

    Returns a dict with keys: ``user_id``, ``email``, ``access_token``,
    ``refresh_token``, and ``headers`` (ready-to-use Authorization header).
    """
    email = f"testuser-{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPassword123!"

    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "Test User",
        },
    )
    assert resp.status_code == 201, f"Registration failed: {resp.text}"

    data = resp.json()["data"]
    return {
        "user_id": data["user"]["id"],
        "email": email,
        "password": password,
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


@pytest_asyncio.fixture(scope="function")
async def second_user(client: AsyncClient) -> dict:
    """Register a second test user for cross-user authorization tests."""
    email = f"otheruser-{uuid.uuid4().hex[:8]}@example.com"
    password = "OtherPassword456!"

    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "Other User",
        },
    )
    assert resp.status_code == 201, f"Registration failed: {resp.text}"

    data = resp.json()["data"]
    return {
        "user_id": data["user"]["id"],
        "email": email,
        "password": password,
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }
