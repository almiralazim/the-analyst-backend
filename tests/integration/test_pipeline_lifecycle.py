"""Integration tests for the pipeline lifecycle.

Covers creating a pipeline run, retrieving pipeline status, listing pipelines,
error handling for non-existent datasets, and authentication enforcement.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


CSV_CONTENT = b"id,name,revenue\n1,Alice,1000\n2,Bob,2000\n3,Charlie,3000\n"


async def _upload_dataset(client: AsyncClient, headers: dict) -> str:
    """Upload a CSV and return the dataset ID."""
    files = {"files": ("pipeline_test.csv", CSV_CONTENT, "text/csv")}
    data = {"name": "Pipeline Test Dataset"}
    resp = await client.post(
        "/api/v1/datasets",
        files=files,
        data=data,
        headers=headers,
    )
    assert resp.status_code == 201, f"Dataset upload failed: {resp.text}"
    return resp.json()["data"]["id"]


# ---------------------------------------------------------------------------
# Create pipeline
# ---------------------------------------------------------------------------


async def test_create_pipeline_returns_queued_or_running(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Creating a pipeline run returns 201 with queued or running status."""
    dataset_id = await _upload_dataset(client, authenticated_user["headers"])

    resp = await client.post(
        "/api/v1/pipelines",
        json={
            "dataset_id": dataset_id,
            "question": "Why did revenue drop last quarter?",
            "plan": "deep_dive",
        },
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["id"]
    assert body["dataset_id"] == dataset_id
    assert body["question"] == "Why did revenue drop last quarter?"
    assert body["status"] in ("queued", "running")


# ---------------------------------------------------------------------------
# Get pipeline status
# ---------------------------------------------------------------------------


async def test_get_pipeline_status_by_id(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Retrieving a pipeline by ID returns 200 with pipeline details."""
    dataset_id = await _upload_dataset(client, authenticated_user["headers"])

    create_resp = await client.post(
        "/api/v1/pipelines",
        json={
            "dataset_id": dataset_id,
            "question": "What are the top revenue drivers?",
            "plan": "deep_dive",
        },
        headers=authenticated_user["headers"],
    )
    pipeline_id = create_resp.json()["data"]["id"]

    resp = await client.get(
        f"/api/v1/pipelines/{pipeline_id}",
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["id"] == pipeline_id
    assert body["dataset_id"] == dataset_id
    assert body["question"] == "What are the top revenue drivers?"
    assert "status" in body
    assert "created_at" in body


# ---------------------------------------------------------------------------
# List pipelines
# ---------------------------------------------------------------------------


async def test_list_pipelines_returns_paginated(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Listing pipelines returns 200 with a paginated response."""
    dataset_id = await _upload_dataset(client, authenticated_user["headers"])

    await client.post(
        "/api/v1/pipelines",
        json={
            "dataset_id": dataset_id,
            "question": "Show me the revenue breakdown.",
            "plan": "deep_dive",
        },
        headers=authenticated_user["headers"],
    )

    resp = await client.get(
        "/api/v1/pipelines",
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1
    assert body["meta"]["total"] >= 1
    assert body["meta"]["page"] == 1


# ---------------------------------------------------------------------------
# Error: non-existent dataset
# ---------------------------------------------------------------------------


async def test_create_pipeline_with_nonexistent_dataset(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Creating a pipeline with a non-existent dataset ID returns 404."""
    fake_dataset_id = str(uuid.uuid4())

    resp = await client.post(
        "/api/v1/pipelines",
        json={
            "dataset_id": fake_dataset_id,
            "question": "Why did revenue drop last quarter?",
            "plan": "deep_dive",
        },
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


async def test_create_pipeline_without_auth_is_rejected(client: AsyncClient):
    """Creating a pipeline without authentication returns 401 or 403."""
    fake_dataset_id = str(uuid.uuid4())

    resp = await client.post(
        "/api/v1/pipelines",
        json={
            "dataset_id": fake_dataset_id,
            "question": "Why did revenue drop last quarter?",
            "plan": "deep_dive",
        },
    )

    assert resp.status_code in (401, 403)
