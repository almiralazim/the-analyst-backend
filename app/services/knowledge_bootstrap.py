"""Knowledge bootstrap: loads corrections, learnings, and context at pipeline start."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset
from app.models.knowledge import Correction, Learning
from app.models.user import User
from app.orchestration.context import PipelineContext


async def bootstrap_context(
    dataset: Dataset,
    user_id: uuid.UUID,
    question: str,
    plan: str,
    db: AsyncSession,
) -> PipelineContext:
    """Build a fully loaded PipelineContext with knowledge from the database.

    This is the enterprise equivalent of ai-analyst's Knowledge Bootstrap skill.
    It loads corrections, learnings, and user preferences so agents have
    full context from the first prompt.
    """
    context = PipelineContext(
        dataset_id=dataset.id,
        user_id=user_id,
        question=question,
        execution_plan=plan,
        duckdb_path=dataset.duckdb_path or "",
        schema_profile=dataset.schema_profile or {},
    )

    # Load corrections for this dataset (and global corrections)
    corrections_result = await db.execute(
        select(Correction)
        .where(Correction.user_id == user_id)
        .where(
            (Correction.dataset_id == dataset.id) | (Correction.dataset_id.is_(None))
        )
        .order_by(Correction.created_at.desc())
        .limit(50)
    )
    context.corrections = [
        {
            "severity": c.severity,
            "category": c.category,
            "description": c.description,
            "prevention_rule": c.prevention_rule,
            "sql_before": c.sql_before,
            "sql_after": c.sql_after,
        }
        for c in corrections_result.scalars().all()
    ]

    # Load learnings
    learnings_result = await db.execute(
        select(Learning)
        .where(Learning.user_id == user_id)
        .order_by(Learning.created_at.desc())
        .limit(50)
    )
    context.learnings = [
        {
            "category": l.category,
            "content": l.content,
            "source": l.source,
        }
        for l in learnings_result.scalars().all()
    ]

    # Load user preferences
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user:
        context.user_preferences = user.preferences or {}

    return context
