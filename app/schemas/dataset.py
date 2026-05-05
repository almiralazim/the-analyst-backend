"""Dataset request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DatasetResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    source_type: str
    status: str
    table_count: int | None = None
    total_rows: int | None = None
    schema_profile: dict | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DatasetListResponse(BaseModel):
    id: uuid.UUID
    name: str
    source_type: str
    status: str
    table_count: int | None = None
    total_rows: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TablePreviewResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    total_rows: int
    page: int
    page_size: int
