"""Integration tests for cross-user authorization.

Verifies that users cannot access resources (datasets, pipelines, results)
belonging to other users. The API returns 404 rather than 403 to avoid
leaking resource existence.
"""

from __future__ import annotations

from httpx import AsyncClient


CSV_CONTENT = b"id,name,amount\n1,Alice,100\n2,Bob,200\n"


async def _upload_as(client: AsyncClient, headers: dict) -> str:
    """Upload a CSV dataset and return its ID."""
    files = {"files": ("authz_test.csv", CSV_CONTENT, "text/csv")}
    data = {"name": "AuthZ Test"}
    resp = await client.post(
        "/api/v1/datasets",
        files=files,
        data=data,
        headers=headers,
    )
    assert resp.status_code == 201, f"Dataset upload failed: {resp.text}"
    return resp.json()["data"]["id"]


# ---------------------------------------------------------------------------
# Dataset authorization
# ---------------------------------------------------------------------------


async def test_user_b_cannot_get_user_a_dataset(
    client: AsyncClient,
    authenticated_user: dict,
    second_user: dict,
):
    """User B gets 404 when trying to retrieve User A's dataset."""
    dataset_id = await _upload_as(client, authenticated_user["headers"])

    resp = await client.get(
        f"/api/v1/datasets/{dataset_id}",
        headers=second_user["headers"],
    )

    assert resp.status_code == 404


async def test_user_b_cannot_delete_user_a_dataset(
    client: AsyncClient,
    authenticated_user: dict,
    second_user: dict,
):
    """User B gets 404 when trying to delete User A's dataset."""
    dataset_id = await _upload_as(client, authenticated_user["headers"])

    resp = await client.delete(
        f"/api/v1/datasets/{dataset_id}",
        headers=second_user["headers"],
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Pipeline authorization
# ---------------------------------------------------------------------------


async def test_user_b_cannot_get_user_a_pipeline(
    client: AsyncClient,
    authenticated_user: dict,
    second_user: dict,
):
    """User B gets 404 when trying to retrieve User A's pipeline."""
    dataset_id = await _upload_as(client, authenticated_user["headers"])

    create_resp = await client.post(
        "/api/v1/pipelines",
        json={
            "dataset_id": dataset_id,
            "question": "What drives revenue?",
            "plan": "deep_dive",
        },
        headers=authenticated_user["headers"],
    )
    assert create_resp.status_code == 201
    pipeline_id = create_resp.json()["data"]["id"]

    resp = await client.get(
        f"/api/v1/pipelines/{pipeline_id}",
        headers=second_user["headers"],
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Results authorization
# ---------------------------------------------------------------------------


async def test_user_b_cannot_get_user_a_results(
    client: AsyncClient,
    authenticated_user: dict,
    second_user: dict,
):
    """User B gets 404 when trying to retrieve User A's pipeline results."""
    dataset_id = await _upload_as(client, authenticated_user["headers"])

    create_resp = await client.post(
        "/api/v1/pipelines",
        json={
            "dataset_id": dataset_id,
            "question": "What drives revenue?",
            "plan": "deep_dive",
        },
        headers=authenticated_user["headers"],
    )
    assert create_resp.status_code == 201
    pipeline_id = create_resp.json()["data"]["id"]

    resp = await client.get(
        f"/api/v1/results/{pipeline_id}",
        headers=second_user["headers"],
    )

    assert resp.status_code == 404
