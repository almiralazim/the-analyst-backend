"""Pipeline request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CreatePipelineRequest(BaseModel):
    dataset_id: uuid.UUID
    question: str = Field(..., min_length=5, max_length=2000)
    plan: Literal["deep_dive", "full_presentation", "validate_only"] = "deep_dive"


class AgentStatusResponse(BaseModel):
    name: str
    tier: int | None = None
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None

    model_config = {"from_attributes": True}


class PipelineResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    question: str
    complexity: str | None = None
    execution_plan: str | None = None
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    confidence_grade: str | None = None
    confidence_score: float | None = None
    error_message: str | None = None
    agents: list[AgentStatusResponse] = []
    created_at: datetime

    model_config = {"from_attributes": True}
