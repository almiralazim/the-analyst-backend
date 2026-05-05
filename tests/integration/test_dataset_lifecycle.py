"""Integration tests for the dataset lifecycle.

Covers CSV upload, listing, detail retrieval, table preview, deletion,
and authentication enforcement on the dataset endpoints.
"""

from __future__ import annotations

from httpx import AsyncClient


CSV_CONTENT = b"id,name,amount\n1,Alice,100\n2,Bob,200\n3,Charlie,300\n"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


async def test_upload_csv_returns_dataset(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Uploading a CSV file returns 201 with a dataset in ready status."""
    files = {"files": ("test.csv", CSV_CONTENT, "text/csv")}
    data = {"name": "Test Dataset"}

    resp = await client.post(
        "/api/v1/datasets",
        files=files,
        data=data,
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["name"] == "Test Dataset"
    assert body["source_type"] == "csv"
    assert body["status"] == "ready"
    assert body["id"]
    assert body["table_count"] >= 1
    assert body["total_rows"] == 3


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


async def test_list_datasets_returns_paginated(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Listing datasets returns 200 with a paginated response."""
    # Upload a dataset first so the list is non-empty.
    files = {"files": ("list_test.csv", CSV_CONTENT, "text/csv")}
    data = {"name": "List Test"}
    await client.post(
        "/api/v1/datasets",
        files=files,
        data=data,
        headers=authenticated_user["headers"],
    )

    resp = await client.get(
        "/api/v1/datasets",
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
# Detail
# ---------------------------------------------------------------------------


async def test_get_dataset_detail(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Retrieving a dataset by ID returns 200 with schema_profile."""
    # Upload
    files = {"files": ("detail_test.csv", CSV_CONTENT, "text/csv")}
    data = {"name": "Detail Test"}
    upload_resp = await client.post(
        "/api/v1/datasets",
        files=files,
        data=data,
        headers=authenticated_user["headers"],
    )
    dataset_id = upload_resp.json()["data"]["id"]

    # Retrieve
    resp = await client.get(
        f"/api/v1/datasets/{dataset_id}",
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["id"] == dataset_id
    assert body["name"] == "Detail Test"
    assert body["schema_profile"] is not None
    assert "tables" in body["schema_profile"]


# ---------------------------------------------------------------------------
# Table preview
# ---------------------------------------------------------------------------


async def test_preview_table_data(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Previewing table data returns 200 with rows and columns."""
    # Upload
    files = {"files": ("preview_test.csv", CSV_CONTENT, "text/csv")}
    data = {"name": "Preview Test"}
    upload_resp = await client.post(
        "/api/v1/datasets",
        files=files,
        data=data,
        headers=authenticated_user["headers"],
    )
    dataset_id = upload_resp.json()["data"]["id"]

    # The CSV filename "preview_test.csv" becomes table name "preview_test"
    resp = await client.get(
        f"/api/v1/datasets/{dataset_id}/tables/preview_test/preview",
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "columns" in body
    assert "rows" in body
    assert body["total_rows"] == 3
    assert len(body["rows"]) == 3
    assert set(body["columns"]) == {"id", "name", "amount"}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def test_delete_dataset(
    client: AsyncClient,
    authenticated_user: dict,
):
    """Deleting a dataset returns success and subsequent GET returns 404."""
    # Upload
    files = {"files": ("delete_test.csv", CSV_CONTENT, "text/csv")}
    data = {"name": "Delete Test"}
    upload_resp = await client.post(
        "/api/v1/datasets",
        files=files,
        data=data,
        headers=authenticated_user["headers"],
    )
    dataset_id = upload_resp.json()["data"]["id"]

    # Delete
    del_resp = await client.delete(
        f"/api/v1/datasets/{dataset_id}",
        headers=authenticated_user["headers"],
    )
    assert del_resp.status_code == 200

    # Verify it's gone
    get_resp = await client.get(
        f"/api/v1/datasets/{dataset_id}",
        headers=authenticated_user["headers"],
    )
    assert get_resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


async def test_upload_without_auth_is_rejected(client: AsyncClient):
    """Uploading a dataset without authentication returns 401 or 403."""
    files = {"files": ("noauth.csv", CSV_CONTENT, "text/csv")}
    data = {"name": "No Auth"}

    resp = await client.post("/api/v1/datasets", files=files, data=data)

    assert resp.status_code in (401, 403)
