"""Shared test fixtures."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

try:
    import pytest_asyncio  # noqa: F401
except ImportError:
    pass

try:
    from httpx import ASGITransport, AsyncClient  # noqa: F401
except ImportError:
    pass

# Set test environment before importing app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key-only-for-automated-tests-not-production-xxxxxxxx"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["DEBUG"] = "true"
os.environ["STORAGE_DIR"] = "./test_storage"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["LLM_DEFAULT_PROVIDER"] = "anthropic"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
def sample_csv_content() -> bytes:
    """A simple CSV file for upload testing."""
    return (
        b"order_id,customer_id,product,quantity,revenue,order_date\n"
        b"ORD-001,CUST-001,Widget A,3,149.97,2025-07-01\n"
        b"ORD-002,CUST-002,Widget B,1,49.99,2025-07-02\n"
        b"ORD-003,CUST-001,Widget A,2,99.98,2025-07-03\n"
        b"ORD-004,CUST-003,Widget C,5,249.95,2025-07-04\n"
        b"ORD-005,CUST-002,Widget B,1,49.99,2025-07-05\n"
    )


@pytest.fixture
def storage_dir(tmp_path) -> Path:
    """Temporary storage directory for tests."""
    d = tmp_path / "test_storage"
    d.mkdir()
    return d
