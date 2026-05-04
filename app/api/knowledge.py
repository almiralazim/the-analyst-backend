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


@router.post("/corrections", response_model=ApiResponse[CorrectionResponse], status_code=201)
@limiter.limit(settings.rate_limit_default)
async def create_correction(
    request: Request,
    body: CreateCorrectionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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


@router.get("/corrections", response_model=PaginatedResponse[CorrectionResponse])
@limiter.limit(settings.rate_limit_default)
async def list_corrections(
    request: Request,
    severity: str | None = Query(None),
    category: str | None = Query(None),
    dataset_id: uuid.UUID | None = Query(None),
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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


@router.post("/learnings", response_model=ApiResponse[LearningResponse], status_code=201)
@limiter.limit(settings.rate_limit_default)
async def create_learning(
    request: Request,
    body: CreateLearningRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    learning = Learning(
        user_id=user.id,
        category=body.category,
        content=body.content,
        source=body.source,
    )
    db.add(learning)
    await db.flush()
    return ApiResponse(data=LearningResponse.model_validate(learning))


@router.get("/learnings", response_model=PaginatedResponse[LearningResponse])
@limiter.limit(settings.rate_limit_default)
async def list_learnings(
    request: Request,
    category: str | None = Query(None),
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
