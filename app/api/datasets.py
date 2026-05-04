"""Dataset endpoints: upload, list, detail, preview, delete."""

from __future__ import annotations

import uuid
from pathlib import Path

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


@router.post("", response_model=ApiResponse[DatasetResponse], status_code=201)
@limiter.limit(settings.rate_limit_heavy)
async def upload_dataset(
    request: Request,
    files: list[UploadFile] = File(...),
    name: str = Form(...),
    description: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate file count
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION_ERROR",
                "message": f"Too many files. Maximum {settings.max_files_per_upload} per upload (got {len(files)}).",
            },
        )

    # Validate file types and sizes
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

    # Trigger async profiling (in-process for MVP)
    from app.services.file_processing import process_dataset_files
    try:
        profile_result = await process_dataset_files(dataset_id, saved_paths, settings.storage_path)
        dataset.duckdb_path = profile_result["duckdb_path"]
        dataset.schema_profile = profile_result["schema_profile"]
        dataset.table_count = profile_result["table_count"]
        dataset.total_rows = profile_result["total_rows"]
        dataset.status = "ready"
    except Exception as e:
        dataset.status = "error"
        dataset.error_message = str(e)

    return ApiResponse(data=DatasetResponse.model_validate(dataset))


@router.get("", response_model=PaginatedResponse[DatasetListResponse])
@limiter.limit(settings.rate_limit_default)
async def list_datasets(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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


@router.get("/{dataset_id}", response_model=ApiResponse[DatasetResponse])
@limiter.limit(settings.rate_limit_default)
async def get_dataset(
    request: Request,
    dataset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Dataset not found"})
    return ApiResponse(data=DatasetResponse.model_validate(dataset))


@router.get("/{dataset_id}/tables/{table_name}/preview", response_model=ApiResponse[TablePreviewResponse])
@limiter.limit(settings.rate_limit_default)
async def preview_table(
    request: Request,
    dataset_id: uuid.UUID,
    table_name: str,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset or not dataset.duckdb_path:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Dataset not found"})

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


@router.delete("/{dataset_id}")
@limiter.limit(settings.rate_limit_default)
async def delete_dataset(
    request: Request,
    dataset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Dataset not found"})

    # Clean up storage
    import shutil
    storage_dir = settings.storage_path / str(dataset_id)
    if storage_dir.exists():
        shutil.rmtree(storage_dir)

    await db.delete(dataset)
    return {"data": {"success": True}}
