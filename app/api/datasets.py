"""Dataset endpoints: upload, list, detail, preview, delete."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.dataset import Dataset
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.common import ApiResponse, PaginatedMeta, PaginatedResponse
from app.schemas.dataset import DatasetListResponse, DatasetResponse, TablePreviewResponse
from app.services.auth import get_current_user

router = APIRouter(prefix="/datasets", tags=["datasets"])

ACCEPTED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls"}
_DATASET_NOT_FOUND = "Dataset not found"


def _validate_upload_files(files: list[UploadFile]) -> None:
    """Validate file count, types, and sizes. Raises HTTPException on failure."""
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION_ERROR",
                "message": f"Too many files. Maximum {settings.max_files_per_upload} per upload (got {len(files)}).",
            },
        )
    total_size = 0
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ACCEPTED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "VALIDATION_ERROR",
                    "message": f"File type {ext} not supported. Accepted: {', '.join(sorted(ACCEPTED_EXTENSIONS))}",
                },
            )
        if f.size and f.size > settings.max_file_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": f"{f.filename} exceeds {settings.max_file_size_mb}MB limit.",
                },
            )
        total_size += f.size or 0
    if total_size > settings.max_total_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "PAYLOAD_TOO_LARGE",
                "message": f"Total upload size exceeds {settings.max_total_upload_mb}MB limit.",
            },
        )


@router.post(
    "",
    response_model=ApiResponse[DatasetResponse],
    response_model_exclude_none=True,
    status_code=201,
    summary="Upload a new dataset",
    response_description="Dataset created and profiled successfully",
    responses={
        400: {"description": "Invalid file type or too many files", "content": {"application/json": {"example": {"error": {"code": "VALIDATION_ERROR", "message": "File type .doc not supported. Accepted: .csv, .tsv, .xls, .xlsx"}}}}},
        413: {"description": "File or total upload size exceeds limit", "content": {"application/json": {"example": {"error": {"code": "PAYLOAD_TOO_LARGE", "message": "sales_data.csv exceeds 500MB limit."}}}}},
        422: {"description": "Validation error (missing name or files)"},
    },
)
@limiter.limit(settings.rate_limit_heavy)
async def upload_dataset(
    request: Request,
    files: list[UploadFile] = File(..., description="Data files to upload (.csv, .tsv, .xlsx, .xls)"),
    name: str = Form(..., description="Human-readable dataset name"),
    description: str = Form("", description="Optional description of the dataset"),
    user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Upload one or more data files to create a new dataset.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Request:** `multipart/form-data`
    - `files` (File[], required): One or more data files. Accepted formats: `.csv`, `.tsv`, `.xlsx`, `.xls`.
      Maximum 10 files per upload. Individual file limit: 500MB. Total upload limit: 1GB.
    - `name` (string, required): Human-readable dataset name.
    - `description` (string, optional): Description of the dataset contents.

    **Response (201):**
    ```json
    {
      "data": {
        "id": "uuid",
        "name": "Q4 Sales Data",
        "description": "Regional sales for Q4 2024",
        "source_type": "csv",
        "status": "ready",
        "table_count": 3,
        "total_rows": 15000,
        "schema_profile": {"tables": [...]},
        "created_at": "2025-01-15T10:30:00Z",
        "updated_at": "2025-01-15T10:30:05Z"
      }
    }
    ```

    **Dataset Status Lifecycle:**
    - `uploading` → `profiling` → `ready` (success)
    - `uploading` → `profiling` → `error` (profiling failed)

    **Errors:**
    - `400 Bad Request`: Unsupported file type or too many files.
    - `413 Payload Too Large`: Individual file or total upload exceeds size limits.
    - `422 Unprocessable Entity`: Missing required form fields.

    **Frontend Integration:**
    - Use `FormData` with `Content-Type: multipart/form-data` (let the browser set the boundary).
    - Show upload progress using `XMLHttpRequest` or `fetch` with a progress stream.
    - After upload, the response includes the final status. If `status` is `"error"`,
      display `error_message` to the user.
    - This endpoint is rate-limited to 10 requests/minute (heavy operation).

    **Example (fetch):**
    ```javascript
    const formData = new FormData();
    formData.append('name', 'Q4 Sales');
    formData.append('files', file1);
    formData.append('files', file2);

    const res = await fetch('/api/v1/datasets', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData,
    });
    ```
    """
    _validate_upload_files(files)

    # Create dataset record
    dataset_id = uuid.uuid4()
    source_type = Path(files[0].filename or "").suffix.lstrip(".").lower()
    if source_type in ("xlsx", "xls"):
        source_type = "excel"

    dataset = Dataset(
        id=dataset_id,
        user_id=user.id,
        name=name,
        description=description or None,
        source_type=source_type,
        status="uploading",
    )
    db.add(dataset)
    await db.flush()

    # Save files to storage
    dataset_dir = settings.storage_path / str(dataset_id) / "raw"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for f in files:
        file_path = dataset_dir / (f.filename or f"file_{len(saved_paths)}")
        content = await f.read()
        file_path.write_bytes(content)
        saved_paths.append(str(file_path))

    dataset.file_path = str(dataset_dir)
    dataset.status = "profiling"
    await db.flush()

    # Process files (sync function — run in thread to avoid blocking the event loop)
    from app.services.file_processing import process_dataset_files
    import asyncio
    try:
        profile_result = await asyncio.to_thread(
            process_dataset_files, dataset_id, saved_paths, settings.storage_path
        )
        dataset.duckdb_path = profile_result["duckdb_path"]
        dataset.schema_profile = profile_result["schema_profile"]
        dataset.table_count = profile_result["table_count"]
        dataset.total_rows = profile_result["total_rows"]
        dataset.status = "ready"
    except Exception as e:
        dataset.status = "error"
        dataset.error_message = str(e)

    return ApiResponse(data=DatasetResponse.model_validate(dataset))


@router.get(
    "",
    response_model=PaginatedResponse[DatasetListResponse],
    response_model_exclude_none=True,
    summary="List all datasets for the current user",
    response_description="Paginated list of datasets owned by the authenticated user",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def list_datasets(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """List all datasets owned by the authenticated user, with pagination.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Query Parameters:**
    - `page` (int, optional, default=1): Page number (1-indexed).
    - `page_size` (int, optional, default=20): Number of items per page.

    **Response (200):**
    ```json
    {
      "data": [
        {
          "id": "uuid",
          "name": "Q4 Sales Data",
          "source_type": "csv",
          "status": "ready",
          "table_count": 3,
          "total_rows": 15000,
          "created_at": "2025-01-15T10:30:00Z"
        }
      ],
      "meta": {
        "total": 42,
        "page": 1,
        "page_size": 20
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.

    **Frontend Integration:**
    - Use `meta.total` and `meta.page_size` to calculate total pages for pagination UI.
    - Results are ordered by `created_at` descending (newest first).
    - Poll or refetch after uploading a new dataset to see it appear in the list.
    """
    offset = (page - 1) * page_size
    query = select(Dataset).where(Dataset.user_id == user.id).order_by(Dataset.created_at.desc())
    count_query = select(func.count()).select_from(Dataset).where(Dataset.user_id == user.id)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset(offset).limit(page_size))
    datasets = result.scalars().all()

    return PaginatedResponse(
        data=[DatasetListResponse.model_validate(d) for d in datasets],
        meta=PaginatedMeta(total=total, page=page, page_size=page_size),
    )


@router.get(
    "/{dataset_id}",
    response_model=ApiResponse[DatasetResponse],
    response_model_exclude_none=True,
    summary="Get dataset details",
    response_description="Full dataset details including schema profile",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Dataset not found or not owned by user", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Dataset not found"}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def get_dataset(
    request: Request,
    dataset_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Get full details for a specific dataset including schema profile.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `dataset_id` (UUID, required): The dataset's unique identifier.

    **Response (200):**
    ```json
    {
      "data": {
        "id": "uuid",
        "name": "Q4 Sales Data",
        "description": "Regional sales for Q4 2024",
        "source_type": "csv",
        "status": "ready",
        "table_count": 3,
        "total_rows": 15000,
        "schema_profile": {
          "tables": [
            {"name": "sales", "columns": [...], "row_count": 5000}
          ]
        },
        "created_at": "2025-01-15T10:30:00Z",
        "updated_at": "2025-01-15T10:30:05Z"
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Dataset does not exist or belongs to another user.

    **Frontend Integration:**
    - Use `schema_profile` to display table/column information in the dataset explorer UI.
    - Check `status` field: only datasets with `status: "ready"` can be used for pipelines.
    - If `status` is `"error"`, display `error_message` to explain what went wrong during profiling.
    """
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": _DATASET_NOT_FOUND})
    return ApiResponse(data=DatasetResponse.model_validate(dataset))


@router.get(
    "/{dataset_id}/tables/{table_name}/preview",
    response_model=ApiResponse[TablePreviewResponse],
    response_model_exclude_none=True,
    summary="Preview table data with pagination",
    response_description="Paginated rows and column names from the specified table",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Dataset not found or table does not exist", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Dataset not found"}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def preview_table(
    request: Request,
    dataset_id: uuid.UUID,
    table_name: str,
    page: int = 1,
    page_size: int = 50,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Preview rows from a specific table within a dataset.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `dataset_id` (UUID, required): The dataset's unique identifier.
    - `table_name` (string, required): Name of the table to preview (from `schema_profile`).

    **Query Parameters:**
    - `page` (int, optional, default=1): Page number (1-indexed).
    - `page_size` (int, optional, default=50): Rows per page (max recommended: 100).

    **Response (200):**
    ```json
    {
      "data": {
        "columns": ["id", "name", "revenue", "date"],
        "rows": [
          [1, "Widget A", 1500.00, "2024-10-01"],
          [2, "Widget B", 2300.50, "2024-10-02"]
        ],
        "total_rows": 5000,
        "page": 1,
        "page_size": 50
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Dataset not found, not owned by user, or DuckDB file not available.

    **Frontend Integration:**
    - Use `columns` array as table headers and `rows` as the data grid body.
    - Each row is an ordered array matching the `columns` order.
    - Use `total_rows` to calculate pagination controls.
    - Table names come from the `schema_profile` in the dataset detail response.
    - Values are returned as their native types (strings, numbers, nulls).
    """
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset or not dataset.duckdb_path:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": _DATASET_NOT_FOUND})

    import duckdb
    offset = (page - 1) * page_size
    conn = duckdb.connect(dataset.duckdb_path, read_only=True)
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()[0]
        rows_result = conn.execute(
            f"SELECT * FROM \"{table_name}\" LIMIT {page_size} OFFSET {offset}"
        )
        columns = [desc[0] for desc in rows_result.description]
        rows = [list(row) for row in rows_result.fetchall()]
    finally:
        conn.close()

    return ApiResponse(data=TablePreviewResponse(
        columns=columns, rows=rows, total_rows=total, page=page, page_size=page_size
    ))


@router.delete(
    "/{dataset_id}",
    summary="Delete a dataset and its storage",
    response_description="Dataset deleted successfully",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Dataset not found or not owned by user", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Dataset not found"}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def delete_dataset(
    request: Request,
    dataset_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Permanently delete a dataset, its files, and all associated storage.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `dataset_id` (UUID, required): The dataset's unique identifier.

    **Response (200):**
    ```json
    {
      "data": {
        "success": true
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Dataset does not exist or belongs to another user.

    **Frontend Integration:**
    - This is a destructive, irreversible operation. Show a confirmation dialog before calling.
    - After successful deletion, remove the dataset from local state/cache and redirect
      to the dataset list.
    - Any pipelines that reference this dataset will lose access to the underlying data.
    - Consider warning the user if active pipelines reference this dataset.
    """
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": _DATASET_NOT_FOUND})

    # Clean up storage
    import shutil
    storage_dir = settings.storage_path / str(dataset_id)
    if storage_dir.exists():
        shutil.rmtree(storage_dir)

    await db.delete(dataset)
    return {"data": {"success": True}}
