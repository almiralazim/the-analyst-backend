"""Knowledge system request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SEVERITY_LEVELS = Literal["critical", "high", "medium", "low"]
CORRECTION_CATEGORIES = Literal[
    "join_error", "filter_missing", "metric_definition", "column_misuse",
    "date_handling", "aggregation_error", "policy_violation", "factual_error", "other"
]
LEARNING_CATEGORIES = Literal[
    "data_patterns", "query_techniques", "business_context",
    "stakeholder_preferences", "visualization_insights", "methodology_notes"
]


class CreateCorrectionRequest(BaseModel):
    dataset_id: uuid.UUID | None = None
    severity: SEVERITY_LEVELS
    category: CORRECTION_CATEGORIES
    description: str = Field(..., min_length=10, max_length=5000)
    sql_before: str | None = None
    sql_after: str | None = None
    prevention_rule: str | None = Field(None, max_length=2000)


class CorrectionResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID | None = None
    severity: str
    category: str
    description: str
    sql_before: str | None = None
    sql_after: str | None = None
    prevention_rule: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateLearningRequest(BaseModel):
    category: LEARNING_CATEGORIES
    content: str = Field(..., min_length=10, max_length=5000)
    source: str | None = Field(None, max_length=255)


class LearningResponse(BaseModel):
    id: uuid.UUID
    category: str
    content: str
    source: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
