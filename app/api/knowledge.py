"""Knowledge system endpoints: corrections and learnings."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.knowledge import Correction, Learning
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.common import ApiResponse, PaginatedMeta, PaginatedResponse
from app.schemas.knowledge import (
    CorrectionResponse,
    CreateCorrectionRequest,
    CreateLearningRequest,
    LearningResponse,
)
from app.services.auth import get_current_user

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post(
    "/corrections",
    response_model=ApiResponse[CorrectionResponse],
    response_model_exclude_none=True,
    status_code=201,
    summary="Log a correction to improve future analyses",
    responses={
        401: {"description": "Missing or invalid access token"},
        422: {"description": "Validation error (missing fields, invalid severity/category)"},
    },
)
@limiter.limit(settings.rate_limit_default)
async def create_correction(
    request: Request,
    body: CreateCorrectionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a correction that the system should learn from for future analyses.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Request Body:**
    - `dataset_id` (UUID, optional): The dataset this correction applies to.
    - `severity` (string, required): One of `"critical"`, `"high"`, `"medium"`, `"low"`.
    - `category` (string, required): One of `"join_error"`, `"filter_missing"`,
      `"metric_definition"`, `"column_misuse"`, `"date_handling"`, `"aggregation_error"`,
      `"policy_violation"`, `"factual_error"`, `"other"`.
    - `description` (string, required): What was wrong. 10-5000 characters.
    - `sql_before` (string, optional): The incorrect SQL that was generated.
    - `sql_after` (string, optional): The corrected SQL.
    - `prevention_rule` (string, optional): A rule the system should follow to avoid this error.
      Max 2000 characters.

    **Response (201):**
    ```json
    {
      "data": {
        "id": "uuid",
        "dataset_id": "uuid",
        "severity": "high",
        "category": "join_error",
        "description": "The query joined orders to customers on the wrong key...",
        "sql_before": "SELECT ... FROM orders JOIN customers ON orders.id = customers.id",
        "sql_after": "SELECT ... FROM orders JOIN customers ON orders.customer_id = customers.id",
        "prevention_rule": "Always join orders to customers using orders.customer_id",
        "created_at": "2025-01-15T10:30:00Z"
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `422 Unprocessable Entity`: Invalid severity, category, or description too short.

    **Frontend Integration:**
    - Show a "Report Issue" button on findings/charts that opens a correction form.
    - Pre-fill `dataset_id` from the current analysis context.
    - Use a dropdown for `severity` and `category` fields.
    - The `sql_before`/`sql_after` fields are optional but help the system learn faster.
    - Corrections are applied to subsequent pipeline runs on the same dataset.
    """
    correction = Correction(
        user_id=user.id,
        dataset_id=body.dataset_id,
        severity=body.severity,
        category=body.category,
        description=body.description,
        sql_before=body.sql_before,
        sql_after=body.sql_after,
        prevention_rule=body.prevention_rule,
    )
    db.add(correction)
    await db.flush()
    return ApiResponse(data=CorrectionResponse.model_validate(correction))


@router.get(
    "/corrections",
    response_model=PaginatedResponse[CorrectionResponse],
    response_model_exclude_none=True,
    summary="List corrections with optional filters",
    responses={
        401: {"description": "Missing or invalid access token"},
    },
)
@limiter.limit(settings.rate_limit_default)
async def list_corrections(
    request: Request,
    severity: str | None = Query(None, description="Filter by severity: critical, high, medium, low"),
    category: str | None = Query(None, description="Filter by category (e.g., join_error, filter_missing)"),
    dataset_id: uuid.UUID | None = Query(None, description="Filter by dataset ID"),
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all corrections logged by the authenticated user, with optional filters.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Query Parameters:**
    - `severity` (string, optional): Filter by severity level.
    - `category` (string, optional): Filter by correction category.
    - `dataset_id` (UUID, optional): Filter corrections for a specific dataset.
    - `page` (int, optional, default=1): Page number (1-indexed).
    - `page_size` (int, optional, default=20): Number of items per page.

    **Response (200):**
    ```json
    {
      "data": [
        {
          "id": "uuid",
          "dataset_id": "uuid",
          "severity": "high",
          "category": "join_error",
          "description": "...",
          "sql_before": "...",
          "sql_after": "...",
          "prevention_rule": "...",
          "created_at": "2025-01-15T10:30:00Z"
        }
      ],
      "meta": {"total": 8, "page": 1, "page_size": 20}
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.

    **Frontend Integration:**
    - Use this to build a "Knowledge Base" or "Corrections History" view.
    - Filter controls map directly to query parameters.
    - Results are ordered by `created_at` descending (newest first).
    - Show severity as color-coded badges and category as tags.
    """
    query = select(Correction).where(Correction.user_id == user.id)
    count_query = select(func.count()).select_from(Correction).where(Correction.user_id == user.id)

    if severity:
        query = query.where(Correction.severity == severity)
        count_query = count_query.where(Correction.severity == severity)
    if category:
        query = query.where(Correction.category == category)
        count_query = count_query.where(Correction.category == category)
    if dataset_id:
        query = query.where(Correction.dataset_id == dataset_id)
        count_query = count_query.where(Correction.dataset_id == dataset_id)

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(query.order_by(Correction.created_at.desc()).offset(offset).limit(page_size))
    corrections = result.scalars().all()

    return PaginatedResponse(
        data=[CorrectionResponse.model_validate(c) for c in corrections],
        meta=PaginatedMeta(total=total, page=page, page_size=page_size),
    )


@router.post(
    "/learnings",
    response_model=ApiResponse[LearningResponse],
    response_model_exclude_none=True,
    status_code=201,
    summary="Record a learning for the knowledge system",
    responses={
        401: {"description": "Missing or invalid access token"},
        422: {"description": "Validation error (missing fields, invalid category)"},
    },
)
@limiter.limit(settings.rate_limit_default)
async def create_learning(
    request: Request,
    body: CreateLearningRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a learning that enriches the system's knowledge for future analyses.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Request Body:**
    - `category` (string, required): One of `"data_patterns"`, `"query_techniques"`,
      `"business_context"`, `"stakeholder_preferences"`, `"visualization_insights"`,
      `"methodology_notes"`.
    - `content` (string, required): The learning content. 10-5000 characters.
    - `source` (string, optional): Where this learning came from (e.g., "Q4 revenue analysis").
      Max 255 characters.

    **Response (201):**
    ```json
    {
      "data": {
        "id": "uuid",
        "category": "business_context",
        "content": "Revenue is recognized at point of delivery, not at order placement",
        "source": "CFO feedback on Q4 analysis",
        "created_at": "2025-01-15T10:30:00Z"
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `422 Unprocessable Entity`: Invalid category or content too short.

    **Frontend Integration:**
    - Provide a "Teach the system" or "Add context" button in the analysis UI.
    - Use `business_context` for domain knowledge (e.g., "fiscal year starts in April").
    - Use `stakeholder_preferences` for presentation preferences (e.g., "CEO prefers bar charts").
    - Learnings are automatically incorporated into subsequent pipeline runs.
    - Show a success toast after creation to confirm the learning was saved.
    """
    learning = Learning(
        user_id=user.id,
        category=body.category,
        content=body.content,
        source=body.source,
    )
    db.add(learning)
    await db.flush()
    return ApiResponse(data=LearningResponse.model_validate(learning))


@router.get(
    "/learnings",
    response_model=PaginatedResponse[LearningResponse],
    response_model_exclude_none=True,
    summary="List learnings with optional category filter",
    responses={
        401: {"description": "Missing or invalid access token"},
    },
)
@limiter.limit(settings.rate_limit_default)
async def list_learnings(
    request: Request,
    category: str | None = Query(None, description="Filter by category (e.g., business_context, data_patterns)"),
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all learnings recorded by the authenticated user, with optional category filter.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Query Parameters:**
    - `category` (string, optional): Filter by learning category.
    - `page` (int, optional, default=1): Page number (1-indexed).
    - `page_size` (int, optional, default=20): Number of items per page.

    **Response (200):**
    ```json
    {
      "data": [
        {
          "id": "uuid",
          "category": "business_context",
          "content": "Revenue is recognized at point of delivery...",
          "source": "CFO feedback on Q4 analysis",
          "created_at": "2025-01-15T10:30:00Z"
        }
      ],
      "meta": {"total": 12, "page": 1, "page_size": 20}
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.

    **Frontend Integration:**
    - Use this to build a "Knowledge Base" view showing what the system has learned.
    - Group learnings by `category` for organized display.
    - Results are ordered by `created_at` descending (newest first).
    - Allow users to review and potentially delete outdated learnings.
    """
    query = select(Learning).where(Learning.user_id == user.id)
    count_query = select(func.count()).select_from(Learning).where(Learning.user_id == user.id)

    if category:
        query = query.where(Learning.category == category)
        count_query = count_query.where(Learning.category == category)

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(query.order_by(Learning.created_at.desc()).offset(offset).limit(page_size))
    learnings = result.scalars().all()

    return PaginatedResponse(
        data=[LearningResponse.model_validate(l) for l in learnings],
        meta=PaginatedMeta(total=total, page=page, page_size=page_size),
    )
