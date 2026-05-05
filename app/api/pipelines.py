"""Pipeline endpoints: create, list, status, cancel, WebSocket progress."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from jose import JWTError, jwt
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db, async_session_factory
from app.models.dataset import Dataset
from app.models.pipeline import AgentExecution, PipelineRun
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.common import ApiResponse, PaginatedMeta, PaginatedResponse
from app.schemas.pipeline import AgentStatusResponse, CreatePipelineRequest, PipelineResponse
from app.services.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipelines", tags=["pipelines"])

# Active WebSocket connections per pipeline
_ws_connections: dict[str, list[WebSocket]] = {}
_background_tasks: set[asyncio.Task] = set()


@router.post(
    "",
    response_model=ApiResponse[PipelineResponse],
    response_model_exclude_none=True,
    status_code=201,
    summary="Create and start a new analysis pipeline",
    responses={
        400: {"description": "Dataset not ready for analysis"},
        404: {"description": "Dataset not found or not owned by user"},
        422: {"description": "Validation error (question too short/long, invalid plan)"},
    },
)
@limiter.limit(settings.rate_limit_heavy)
async def create_pipeline(
    request: Request,
    body: CreatePipelineRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a new analysis pipeline that runs AI agents against a dataset.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Request Body:**
    - `dataset_id` (UUID, required): ID of a dataset with `status: "ready"`.
    - `question` (string, required): The analytical question to answer. 5-2000 characters.
    - `plan` (string, optional, default="deep_dive"): Execution plan type.
      One of: `"deep_dive"`, `"full_presentation"`, `"validate_only"`.

    **Execution Plans:**
    - `deep_dive`: Full 10-agent pipeline with findings, charts, narrative, and validation.
    - `full_presentation`: Same as deep_dive but optimized for presentation output.
    - `validate_only`: Runs only validation agents — useful for verifying existing analyses.

    **Response (201):**
    ```json
    {
      "data": {
        "id": "uuid",
        "dataset_id": "uuid",
        "question": "What drove revenue growth in Q4?",
        "execution_plan": "deep_dive",
        "status": "queued",
        "created_at": "2025-01-15T10:30:00Z",
        "agents": []
      }
    }
    ```

    **Pipeline Status Lifecycle:**
    `queued` → `running` → `completed` | `failed` | `cancelled`

    **Errors:**
    - `400 Bad Request`: Dataset exists but is not in `"ready"` status.
    - `404 Not Found`: Dataset does not exist or belongs to another user.
    - `422 Unprocessable Entity`: Question too short (<5 chars) or too long (>2000 chars),
      or invalid plan value.

    **Frontend Integration:**
    - After creating a pipeline, immediately connect to the WebSocket endpoint
      `ws://host/api/v1/pipelines/{id}/ws?token=<access_token>` to receive real-time progress.
    - Alternatively, poll `GET /api/v1/pipelines/{id}` every 3-5 seconds.
    - The pipeline runs asynchronously — the 201 response returns immediately with `status: "queued"`.
    - This endpoint is rate-limited to 10 requests/minute (heavy operation).
    """
    # Verify dataset exists and belongs to user
    result = await db.execute(
        select(Dataset).where(Dataset.id == body.dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Dataset not found"})
    if dataset.status != "ready":
        raise HTTPException(
            status_code=400,
            detail={"code": "VALIDATION_ERROR", "message": f"Dataset is not ready (status: {dataset.status})"},
        )

    # Create pipeline run
    pipeline = PipelineRun(
        user_id=user.id,
        dataset_id=body.dataset_id,
        question=body.question,
        execution_plan=body.plan,
        status="queued",
    )
    db.add(pipeline)
    await db.flush()

    # Launch pipeline execution in background
    task = asyncio.create_task(_run_pipeline(pipeline.id, dataset, user.id, body.question, body.plan))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return ApiResponse(data=PipelineResponse(
        id=pipeline.id,
        dataset_id=pipeline.dataset_id,
        question=pipeline.question,
        execution_plan=pipeline.execution_plan,
        status=pipeline.status,
        created_at=pipeline.created_at,
    ))


@router.get(
    "",
    response_model=PaginatedResponse[PipelineResponse],
    response_model_exclude_none=True,
    summary="List all pipelines for the current user",
    responses={
        401: {"description": "Missing or invalid access token"},
    },
)
@limiter.limit(settings.rate_limit_default)
async def list_pipelines(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = 1,
    page_size: int = 20,
):
    """List all pipeline runs for the authenticated user, with pagination.

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
          "dataset_id": "uuid",
          "question": "What drove revenue growth in Q4?",
          "complexity": "moderate",
          "execution_plan": "deep_dive",
          "status": "completed",
          "confidence_grade": "A",
          "confidence_score": 0.92,
          "started_at": "2025-01-15T10:30:01Z",
          "completed_at": "2025-01-15T10:31:45Z",
          "agents": [
            {"name": "data_explorer", "tier": 1, "status": "completed", "duration_ms": 4500}
          ],
          "created_at": "2025-01-15T10:30:00Z"
        }
      ],
      "meta": {"total": 15, "page": 1, "page_size": 20}
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.

    **Frontend Integration:**
    - Results are ordered by `created_at` descending (newest first).
    - Use `status` to show pipeline state badges (queued, running, completed, failed, cancelled).
    - Use `confidence_grade` (A/B/C/D/F) for a quick quality indicator.
    - The `agents` array shows per-agent execution status for progress visualization.
    """
    offset = (page - 1) * page_size
    query = (
        select(PipelineRun)
        .where(PipelineRun.user_id == user.id)
        .options(selectinload(PipelineRun.agent_executions))
        .order_by(PipelineRun.created_at.desc())
    )
    count_query = select(func.count()).select_from(PipelineRun).where(PipelineRun.user_id == user.id)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset(offset).limit(page_size))
    pipelines = result.scalars().unique().all()

    return PaginatedResponse(
        data=[_pipeline_to_response(p) for p in pipelines],
        meta=PaginatedMeta(total=total, page=page, page_size=page_size),
    )


@router.get(
    "/{pipeline_id}",
    response_model=ApiResponse[PipelineResponse],
    response_model_exclude_none=True,
    summary="Get pipeline status and details",
    responses={
        401: {"description": "Missing or invalid access token"},
        404: {"description": "Pipeline not found or not owned by user"},
    },
)
@limiter.limit(settings.rate_limit_default)
async def get_pipeline(
    request: Request,
    pipeline_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get the current status and details of a specific pipeline run.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `pipeline_id` (UUID, required): The pipeline's unique identifier.

    **Response (200):**
    ```json
    {
      "data": {
        "id": "uuid",
        "dataset_id": "uuid",
        "question": "What drove revenue growth in Q4?",
        "complexity": "moderate",
        "execution_plan": "deep_dive",
        "status": "running",
        "started_at": "2025-01-15T10:30:01Z",
        "agents": [
          {"name": "data_explorer", "tier": 1, "status": "completed", "duration_ms": 4500},
          {"name": "hypothesis_generator", "tier": 2, "status": "running"}
        ],
        "created_at": "2025-01-15T10:30:00Z"
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Pipeline does not exist or belongs to another user.

    **Frontend Integration:**
    - Use this for polling-based progress tracking (every 3-5 seconds while `status` is `"running"`).
    - The `agents` array updates as each agent starts and completes.
    - When `status` changes to `"completed"`, fetch results from `GET /api/v1/results/{pipeline_id}`.
    - When `status` is `"failed"`, display `error_message` to the user.
    - Prefer WebSocket over polling for real-time UX.
    """
    result = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.id == pipeline_id, PipelineRun.user_id == user.id)
        .options(selectinload(PipelineRun.agent_executions))
    )
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Pipeline not found"})
    return ApiResponse(data=_pipeline_to_response(pipeline))


@router.post(
    "/{pipeline_id}/cancel",
    summary="Cancel a running pipeline",
    responses={
        401: {"description": "Missing or invalid access token"},
        404: {"description": "Pipeline not found or not owned by user"},
    },
)
@limiter.limit(settings.rate_limit_default)
async def cancel_pipeline(
    request: Request,
    pipeline_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Cancel a pipeline that is currently queued or running.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `pipeline_id` (UUID, required): The pipeline's unique identifier.

    **Response (200) — Successfully cancelled:**
    ```json
    {
      "data": {"success": true, "status": "cancelled"}
    }
    ```

    **Response (200) — Already finished (no-op):**
    ```json
    {
      "data": {"success": false, "status": "completed", "message": "Pipeline already finished"}
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Pipeline does not exist or belongs to another user.

    **Frontend Integration:**
    - Cancellation is idempotent — calling it on an already-finished pipeline returns success=false.
    - After cancellation, the pipeline status becomes `"cancelled"` and no further agent work runs.
    - The WebSocket connection (if open) will receive a `pipeline_failed` event with cancellation info.
    - Show a "Cancel" button only when `status` is `"queued"` or `"running"`.
    """
    result = await db.execute(
        select(PipelineRun).where(PipelineRun.id == pipeline_id, PipelineRun.user_id == user.id)
    )
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Pipeline not found"})

    if pipeline.status in ("completed", "failed", "cancelled"):
        return {"data": {"success": False, "status": pipeline.status, "message": "Pipeline already finished"}}

    pipeline.status = "cancelled"
    pipeline.completed_at = datetime.now(timezone.utc)
    return {"data": {"success": True, "status": "cancelled"}}


# --- WebSocket for real-time pipeline progress ---

@router.websocket("/{pipeline_id}/ws")
async def pipeline_websocket(websocket: WebSocket, pipeline_id: str, token: str = Query("")):
    """WebSocket endpoint for real-time pipeline progress events.

    **Authentication:** Via `token` query parameter (access token).

    **Connection URL:**
    ```
    ws://host/api/v1/pipelines/{pipeline_id}/ws?token=<access_token>
    ```

    **Connection Flow:**
    1. Client connects with a valid access token as query parameter.
    2. Server validates token and verifies pipeline ownership.
    3. On success, connection is accepted and events stream in real-time.
    4. Server sends keepalive pings every 30 seconds.

    **Event Types:**
    ```json
    {"event": "agent_started", "agent": "data_explorer", "tier": 1, "timestamp": "..."}
    {"event": "agent_completed", "agent": "data_explorer", "duration_ms": 4500, "timestamp": "..."}
    {"event": "agent_failed", "agent": "hypothesis_gen", "error": "...", "timestamp": "..."}
    {"event": "pipeline_completed", "pipeline_id": "...", "confidence_grade": "A", "duration_ms": 95000, "timestamp": "..."}
    {"event": "pipeline_failed", "pipeline_id": "...", "error": "...", "timestamp": "..."}
    {"event": "ping", "timestamp": "..."}
    ```

    **Close Codes:**
    - `4001`: Authentication failed (missing/invalid/expired token).
    - `4003`: Forbidden (pipeline belongs to another user).
    - `4004`: Pipeline not found.

    **Frontend Integration:**
    - Connect immediately after creating a pipeline.
    - Use `agent_started`/`agent_completed` events to update a progress stepper UI.
    - On `pipeline_completed`, close the WebSocket and fetch full results.
    - Implement reconnection with exponential backoff (1s, 2s, 4s, max 30s).
    - Handle token expiry: if connection closes with 4001, refresh the token and reconnect.
    """
    # Authenticate via query param token
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return

    try:
        from app.services.auth import ALGORITHM
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id or payload.get("type") != "access":
            await websocket.close(code=4001, reason="Invalid token")
            return
    except JWTError:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # Verify the authenticated user owns the requested pipeline
    async with async_session_factory() as db:
        result = await db.execute(
            select(PipelineRun).where(PipelineRun.id == uuid.UUID(pipeline_id))
        )
        pipeline = result.scalar_one_or_none()
        if not pipeline:
            await websocket.close(code=4004, reason="Not found")
            return
        if str(pipeline.user_id) != user_id:
            await websocket.close(code=4003, reason="Forbidden")
            return

    await websocket.accept()

    # Register connection
    pid = str(pipeline_id)
    if pid not in _ws_connections:
        _ws_connections[pid] = []
    _ws_connections[pid].append(websocket)

    try:
        # Keep connection alive until client disconnects or pipeline completes
        while True:
            # Wait for client messages (ping/pong or close)
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"event": "ping", "timestamp": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        pass
    finally:
        if pid in _ws_connections:
            _ws_connections[pid] = [ws for ws in _ws_connections[pid] if ws != websocket]
            if not _ws_connections[pid]:
                del _ws_connections[pid]


async def broadcast_progress(pipeline_id: str, event: dict) -> None:
    """Broadcast a progress event to all WebSocket connections for a pipeline."""
    pid = str(pipeline_id)
    if pid not in _ws_connections:
        return

    dead = []
    for ws in _ws_connections[pid]:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)

    for ws in dead:
        _ws_connections[pid].remove(ws)


# --- Background pipeline execution ---

async def _run_pipeline(
    pipeline_id: uuid.UUID,
    dataset: Dataset,
    user_id: uuid.UUID,
    question: str,
    plan: str,
) -> None:
    """Background task that executes the full agent pipeline."""
    from app.agents.runner import execute_agent
    from app.orchestration.context import PipelineContext
    from app.orchestration.dag_resolver import filter_agents_by_plan
    from app.orchestration.executor import execute_pipeline, PipelineError
    from app.orchestration.registry import load_registry
    from app.services.knowledge_bootstrap import bootstrap_context

    async with async_session_factory() as db:
        try:
            # Load pipeline record
            result = await db.execute(select(PipelineRun).where(PipelineRun.id == pipeline_id))
            pipeline = result.scalar_one()
            pipeline.status = "running"
            pipeline.started_at = datetime.now(timezone.utc)
            await db.commit()

            # Bootstrap context with knowledge
            context = await bootstrap_context(dataset, user_id, question, plan, db)
            context.run_id = pipeline_id

            # Load and filter agents
            all_agents = load_registry()
            agents = filter_agents_by_plan(all_agents, plan)

            # Create agent execution records
            for agent in agents:
                ae = AgentExecution(
                    pipeline_run_id=pipeline_id,
                    agent_name=agent.name,
                    tier=agent.tier if agent.tier >= 0 else None,
                    status="queued",
                )
                db.add(ae)
            await db.commit()

            # Progress callback
            async def on_progress(event: dict):
                await broadcast_progress(str(pipeline_id), event)
                # Update agent execution records
                if event.get("event") == "agent_started":
                    await _update_agent_status(db, pipeline_id, event["agent"], "running")
                elif event.get("event") == "agent_completed":
                    await _update_agent_status(
                        db, pipeline_id, event["agent"], "completed",
                        duration_ms=event.get("duration_ms"),
                    )
                elif event.get("event") == "agent_failed":
                    await _update_agent_status(
                        db, pipeline_id, event["agent"], "failed",
                        error=event.get("error"),
                    )

            # Execute pipeline
            context = await execute_pipeline(agents, context, execute_agent, on_progress)

            # Store results
            from app.services.result_builder import build_and_store_results
            await build_and_store_results(db, pipeline_id, context)

            # Update pipeline status
            pipeline.status = "completed"
            pipeline.completed_at = datetime.now(timezone.utc)

            # Compute confidence from programmatic validation results
            if context.validation_result:
                from app.helpers.confidence_scorer import compute_confidence
                validation_data = context.validation_result.get(
                    "programmatic_validation", context.validation_result
                )
                confidence = compute_confidence(validation_data)
                pipeline.confidence_grade = confidence.grade
                pipeline.confidence_score = confidence.score

            await db.commit()

            await broadcast_progress(str(pipeline_id), {
                "event": "pipeline_completed",
                "pipeline_id": str(pipeline_id),
                "confidence_grade": pipeline.confidence_grade,
                "duration_ms": int((pipeline.completed_at - pipeline.started_at).total_seconds() * 1000),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        except PipelineError as e:
            pipeline.status = "failed"
            pipeline.error_message = str(e)
            pipeline.completed_at = datetime.now(timezone.utc)
            await db.commit()

            await broadcast_progress(str(pipeline_id), {
                "event": "pipeline_failed",
                "pipeline_id": str(pipeline_id),
                "error": str(e),
                "failed_at_tier": e.tier,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        except Exception as e:
            logger.exception("Pipeline %s failed unexpectedly", pipeline_id)
            pipeline.status = "failed"
            pipeline.error_message = f"Unexpected error: {str(e)}"
            pipeline.completed_at = datetime.now(timezone.utc)
            await db.commit()

            await broadcast_progress(str(pipeline_id), {
                "event": "pipeline_failed",
                "pipeline_id": str(pipeline_id),
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })


async def _update_agent_status(
    db: AsyncSession,
    pipeline_id: uuid.UUID,
    agent_name: str,
    status: str,
    duration_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Update an agent execution record."""
    result = await db.execute(
        select(AgentExecution).where(
            AgentExecution.pipeline_run_id == pipeline_id,
            AgentExecution.agent_name == agent_name,
        )
    )
    ae = result.scalar_one_or_none()
    if ae:
        ae.status = status
        if status == "running":
            ae.started_at = datetime.now(timezone.utc)
        elif status in ("completed", "failed"):
            ae.completed_at = datetime.now(timezone.utc)
        if duration_ms is not None:
            ae.duration_ms = duration_ms
        if error:
            ae.error_message = error
        await db.commit()


def _pipeline_to_response(pipeline: PipelineRun) -> PipelineResponse:
    """Convert a PipelineRun model to a PipelineResponse schema."""
    agents = []
    if pipeline.agent_executions:
        agents = [
            AgentStatusResponse(
                name=ae.agent_name,
                tier=ae.tier,
                status=ae.status,
                started_at=ae.started_at,
                completed_at=ae.completed_at,
                duration_ms=ae.duration_ms,
            )
            for ae in sorted(pipeline.agent_executions, key=lambda x: (x.tier or 0, x.agent_name))
        ]

    return PipelineResponse(
        id=pipeline.id,
        dataset_id=pipeline.dataset_id,
        question=pipeline.question,
        complexity=pipeline.complexity,
        execution_plan=pipeline.execution_plan,
        status=pipeline.status,
        started_at=pipeline.started_at,
        completed_at=pipeline.completed_at,
        confidence_grade=pipeline.confidence_grade,
        confidence_score=pipeline.confidence_score,
        error_message=pipeline.error_message,
        agents=agents,
        created_at=pipeline.created_at,
    )
