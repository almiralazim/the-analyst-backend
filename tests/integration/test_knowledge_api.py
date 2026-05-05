"""Integration tests for the knowledge API (corrections and learnings).

Covers creating and listing corrections and learnings, and verifies
that unauthenticated requests are rejected.
"""

from __future__ import annotations

from httpx import AsyncClient


CORRECTIONS_URL = "/api/v1/knowledge/corrections"
LEARNINGS_URL = "/api/v1/knowledge/learnings"


def _correction_payload(**overrides) -> dict:
    """Return a valid correction request body, with optional overrides."""
    base = {
        "severity": "high",
        "category": "metric_definition",
        "description": "Revenue should exclude refunds",
        "prevention_rule": "Always subtract refunds",
    }
    base.update(overrides)
    return base


def _learning_payload(**overrides) -> dict:
    """Return a valid learning request body, with optional overrides."""
    base = {
        "category": "data_patterns",
        "content": "Q3 always shows seasonal dip",
        "source": "manual",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


async def test_create_correction(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Creating a correction returns 201 with the correction data."""
    resp = await client.post(
        CORRECTIONS_URL,
        json=_correction_payload(),
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["id"]
    assert body["severity"] == "high"
    assert body["category"] == "metric_definition"
    assert body["description"] == "Revenue should exclude refunds"
    assert (
        body["prevention_rule"] == "Always subtract refunds"
    )
    assert body["created_at"]


async def test_list_corrections_returns_created(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Listing corrections includes a previously created one."""
    create_resp = await client.post(
        CORRECTIONS_URL,
        json=_correction_payload(),
        headers=authenticated_user["headers"],
    )
    created_id = create_resp.json()["data"]["id"]

    list_resp = await client.get(
        CORRECTIONS_URL,
        headers=authenticated_user["headers"],
    )

    assert list_resp.status_code == 200
    body = list_resp.json()
    assert "data" in body
    assert "meta" in body
    ids = [c["id"] for c in body["data"]]
    assert created_id in ids


# ---------------------------------------------------------------------------
# Learnings
# ---------------------------------------------------------------------------


async def test_create_learning(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Creating a learning returns 201 with the learning data."""
    resp = await client.post(
        LEARNINGS_URL,
        json=_learning_payload(),
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["id"]
    assert body["category"] == "data_patterns"
    assert (
        body["content"] == "Q3 always shows seasonal dip"
    )
    assert body["source"] == "manual"
    assert body["created_at"]


async def test_list_learnings_returns_created(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Listing learnings includes a previously created one."""
    create_resp = await client.post(
        LEARNINGS_URL,
        json=_learning_payload(),
        headers=authenticated_user["headers"],
    )
    created_id = create_resp.json()["data"]["id"]

    list_resp = await client.get(
        LEARNINGS_URL,
        headers=authenticated_user["headers"],
    )

    assert list_resp.status_code == 200
    body = list_resp.json()
    assert "data" in body
    assert "meta" in body
    ids = [item["id"] for item in body["data"]]
    assert created_id in ids


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


async def test_create_correction_without_auth_is_rejected(client: AsyncClient):
    """Creating a correction without authentication returns 401 or 403."""
    resp = await client.post(
        CORRECTIONS_URL,
        json=_correction_payload(),
    )

    assert resp.status_code in (401, 403)
