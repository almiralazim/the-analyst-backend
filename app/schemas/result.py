"""Result response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class FindingResponse(BaseModel):
    id: str
    headline: str
    detail: str
    impact: str
    confidence: float
    supporting_data: dict | None = None
    sources: list[str] = []


class ChartResponse(BaseModel):
    id: str
    title: str
    type: str
    url: str
    width: int = 1500
    height: int = 900
    agent: str


class RecommendationResponse(BaseModel):
    id: str
    action: str
    rationale: str
    confidence: str
    impact: str
    owner: str | None = None
    deadline: str | None = None


class ValidationLayerResponse(BaseModel):
    status: str
    checks: int = 0
    failures: int = 0
    warnings: int = 0
    checked_combinations: int | None = None
    paradoxes_found: int | None = None


class ValidationWarningResponse(BaseModel):
    layer: str
    message: str
    severity: str


class ValidationResponse(BaseModel):
    structural: ValidationLayerResponse
    logical: ValidationLayerResponse
    business_rules: ValidationLayerResponse
    simpsons_paradox: ValidationLayerResponse
    overall_grade: str
    overall_score: float
    warnings: list[ValidationWarningResponse] = []


class NarrativeResponse(BaseModel):
    executive_summary: str
    detailed_findings: str
    recommendations: list[RecommendationResponse] = []


class AgentSummaryResponse(BaseModel):
    agent: str
    status: str
    duration_ms: int | None = None


class FullResultsResponse(BaseModel):
    pipeline_id: uuid.UUID
    question: str
    status: str
    confidence_grade: str | None = None
    confidence_score: float | None = None
    duration_ms: int | None = None
    findings: list[FindingResponse] = []
    charts: list[ChartResponse] = []
    narrative: NarrativeResponse | None = None
    validation: ValidationResponse | None = None
    agent_summary: list[AgentSummaryResponse] = []


class ResultsMetaResponse(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    execution_plan: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
