"""Pipeline endpoints: create, list, status, cancel, WebSocket progress."""

from __future__ import annotations

import asyncio
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
from app.llm.model_registry import ModelRegistry
from app.models.dataset import Dataset
from app.models.pipeline import AgentExecution, PipelineRun
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.common import ApiResponse, PaginatedMeta, PaginatedResponse
from app.schemas.pipeline import AgentStatusResponse, CreatePipelineRequest, PipelineResponse
from app.services.auth import get_current_user

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.orchestration.agent_gate import GatingDecision

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
    response_description="Pipeline created and queued for execution",
    responses={
        400: {"description": "Dataset not ready for analysis", "content": {"application/json": {"example": {"error": {"code": "VALIDATION_ERROR", "message": "Dataset is not ready (status: profiling)"}}}}},
        404: {"description": "Dataset not found or not owned by user", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Dataset not found"}}}}},
        422: {"description": "Validation error (question too short/long, invalid plan)", "content": {"application/json": {"example": {"detail": [{"loc": ["body", "question"], "msg": "ensure this value has at least 5 characters", "type": "value_error.any_str.min_length"}]}}}},
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

    # Validate model selection
    registry = ModelRegistry()
    if not registry.is_valid_selection(body.model):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": (
                    f"Invalid model selection '{body.model}'. "
                    "Use 'auto', a provider name (anthropic, openai, gemini, groq), "
                    "or a specific model ID."
                ),
            },
        )

    # Check provider availability
    if body.model != "auto":
        provider_to_check = body.model
        if body.model not in registry.all_provider_names:
            # It's a model ID — resolve to provider
            provider_to_check = registry.get_provider_for_model(body.model)

        if provider_to_check and not registry.is_provider_available(provider_to_check):
            available = [
                p.name for p in registry.get_available_providers()
            ]
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "PROVIDER_UNAVAILABLE",
                    "message": (
                        f"Provider '{provider_to_check}' is not available. "
                        f"Configured providers: {available}"
                    ),
                },
            )

    # Create pipeline run
    pipeline = PipelineRun(
        user_id=user.id,
        dataset_id=body.dataset_id,
        question=body.question,
        execution_plan=body.plan,
        model_selection=body.model,
        status="queued",
    )
    db.add(pipeline)
    await db.flush()

    # Launch pipeline execution in background
    task = asyncio.create_task(
        _run_pipeline(
            pipeline.id, dataset, user.id, body.question,
            body.plan, body.model, body.force_full_analysis,
        )
    )
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
    response_description="Paginated list of pipeline runs with agent status",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
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
    response_description="Pipeline details with current status and per-agent progress",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Pipeline not found or not owned by user", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Pipeline not found"}}}}},
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
    response_description="Cancellation result with updated pipeline status",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Pipeline not found or not owned by user", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Pipeline not found"}}}}},
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

def _build_gating_decision_payload(gating_decision) -> dict:
    """Serialize a GatingDecision into a dict for events/metadata."""
    return {
        "intent": gating_decision.intent.value,
        "complexity": gating_decision.complexity.value,
        "dispatched_agents": gating_decision.dispatched_agents,
        "skipped_agents": [
            {"name": s.name, "tier": s.tier, "reason": s.reason}
            for s in gating_decision.skipped_agents
        ],
        "gate_duration_ms": gating_decision.gate_duration_ms,
        "reasoning": gating_decision.reasoning,
    }


async def _broadcast_gating_events(
    pipeline_id_str: str, gating_decision
) -> None:
    """Broadcast gating decision and individual agent_skipped events."""
    payload = _build_gating_decision_payload(gating_decision)
    payload["event"] = "gating_decision"
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    await broadcast_progress(pipeline_id_str, payload)

    for skipped in gating_decision.skipped_agents:
        await broadcast_progress(pipeline_id_str, {
            "event": "agent_skipped",
            "agent": skipped.name,
            "tier": skipped.tier,
            "reason": skipped.reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


async def _apply_gating_and_filter(
    context,
    agents: list,
    remaining_agents: list,
    plan: str,
    pipeline_id: uuid.UUID,
    db: AsyncSession,
):
    """Apply agent gate and filter remaining agents. Returns (filtered_agents, decision)."""
    pipeline_id_str = str(pipeline_id)
    gating_decision = await _apply_agent_gate(
        context, agents, plan, pipeline_id_str,
    )
    if gating_decision is None:
        return remaining_agents, None

    await _broadcast_gating_events(pipeline_id_str, gating_decision)

    dispatched_set = set(gating_decision.dispatched_agents)
    gated_out_agents = [a for a in remaining_agents if a.name not in dispatched_set]
    filtered_agents = [a for a in remaining_agents if a.name in dispatched_set]

    for agent in gated_out_agents:
        await _update_agent_status(db, pipeline_id, agent.name, "gated_out")

    return filtered_agents, gating_decision


def _compute_gating_metrics(context, agents: list, gating_decision) -> dict:
    """Compute token usage and gating metrics."""
    total_input_tokens = 0
    total_output_tokens = 0
    for agent_output in context.agent_outputs.values():
        if isinstance(agent_output, dict):
            usage = agent_output.get("llm_usage", {})
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)

    agents_available_count = len([a for a in agents if a.name != "question-framing"])
    agents_dispatched_count = (
        len(gating_decision.dispatched_agents)
        if gating_decision is not None
        else agents_available_count
    )
    agents_skipped_count = agents_available_count - agents_dispatched_count
    gate_duration_ms = (
        gating_decision.gate_duration_ms if gating_decision is not None else 0
    )

    avg_tokens_per_agent = 0
    total_tokens = total_input_tokens + total_output_tokens
    if agents_dispatched_count > 0 and total_tokens > 0:
        avg_tokens_per_agent = total_tokens // agents_dispatched_count
    estimated_token_savings = avg_tokens_per_agent * agents_skipped_count

    return {
        "total_token_count": total_tokens,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "agents_dispatched_count": agents_dispatched_count,
        "agents_available_count": agents_available_count,
        "agents_skipped_count": agents_skipped_count,
        "gate_duration_ms": gate_duration_ms,
        "estimated_token_savings": estimated_token_savings,
    }


async def _handle_progress_event(
    db: AsyncSession, pipeline_id: uuid.UUID, event: dict
) -> None:
    """Route a progress event to the appropriate agent status update."""
    await broadcast_progress(str(pipeline_id), event)
    _PROGRESS_HANDLERS = {
        "agent_started": lambda e: _update_agent_status(
            db, pipeline_id, e["agent"], "running"
        ),
        "agent_completed": lambda e: _update_agent_status(
            db, pipeline_id, e["agent"], "completed", duration_ms=e.get("duration_ms")
        ),
        "agent_failed": lambda e: _update_agent_status(
            db, pipeline_id, e["agent"], "failed", error=e.get("error")
        ),
    }
    handler = _PROGRESS_HANDLERS.get(event.get("event"))
    if handler:
        await handler(event)


async def _finalize_pipeline(
    db: AsyncSession,
    pipeline: PipelineRun,
    pipeline_id: uuid.UUID,
    context,
    agents: list,
    gating_decision,
) -> None:
    """Store metadata, compute confidence, commit, and broadcast completion."""
    pipeline.status = "completed"
    pipeline.completed_at = datetime.now(timezone.utc)

    metadata = pipeline.context_snapshot or {}
    if gating_decision is not None:
        metadata["gating_decision"] = _build_gating_decision_payload(gating_decision)

    metrics = _compute_gating_metrics(context, agents, gating_decision)
    metadata["gating_metrics"] = metrics

    if metrics["agents_skipped_count"] > 0:
        logger.info(
            "Pipeline %s gating metrics: dispatched %d/%d agents, "
            "gate took %dms, estimated %d tokens saved",
            pipeline_id,
            metrics["agents_dispatched_count"],
            metrics["agents_available_count"],
            metrics["gate_duration_ms"],
            metrics["estimated_token_savings"],
        )

    pipeline.context_snapshot = metadata

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


async def _handle_pipeline_failure(
    db: AsyncSession, pipeline: PipelineRun, pipeline_id: uuid.UUID, error: Exception
) -> None:
    """Mark pipeline as failed, commit, and broadcast failure event."""
    from app.orchestration.executor import PipelineError

    logger.exception("Pipeline %s failed", pipeline_id)
    pipeline.status = "failed"
    pipeline.error_message = str(error)
    pipeline.completed_at = datetime.now(timezone.utc)
    await db.commit()

    event: dict = {
        "event": "pipeline_failed",
        "pipeline_id": str(pipeline_id),
        "error": str(error),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(error, PipelineError):
        event["failed_at_tier"] = error.tier
    await broadcast_progress(str(pipeline_id), event)


async def _run_pipeline(
    pipeline_id: uuid.UUID,
    dataset: Dataset,
    user_id: uuid.UUID,
    question: str,
    plan: str,
    model_selection: str = "auto",
    force_full_analysis: bool = False,
) -> None:
    """Background task that executes the full agent pipeline."""
    from app.orchestration.context import PipelineContext
    from app.orchestration.dag_resolver import filter_agents_by_plan
    from app.orchestration.executor import execute_pipeline, PipelineError
    from app.orchestration.registry import load_registry, get_agent_tiers
    from app.llm.model_router import ModelRouter
    from app.llm.factory import get_llm_provider
    from app.services.knowledge_bootstrap import bootstrap_context

    async with async_session_factory() as db:
        try:
            result = await db.execute(select(PipelineRun).where(PipelineRun.id == pipeline_id))
            pipeline = result.scalar_one()
            pipeline.status = "running"
            pipeline.started_at = datetime.now(timezone.utc)
            await db.commit()

            context = await bootstrap_context(dataset, user_id, question, plan, db)
            context.run_id = pipeline_id

            all_agents = load_registry()
            agents = filter_agents_by_plan(all_agents, plan)

            # Resolve model assignments
            router = ModelRouter()
            assignments = router.resolve_assignments(
                [a.name for a in agents], model_selection, get_agent_tiers()
            )
            assignment_map = {a.agent_name: a for a in assignments}

            # Create agent execution records
            for agent in agents:
                db.add(AgentExecution(
                    pipeline_run_id=pipeline_id,
                    agent_name=agent.name,
                    tier=agent.tier if agent.tier >= 0 else None,
                    status="queued",
                ))
            await db.commit()

            async def on_progress(event: dict):
                await _handle_progress_event(db, pipeline_id, event)

            def agent_llm_factory(agent_name: str):
                assignment = assignment_map.get(agent_name)
                if assignment:
                    return get_llm_provider(assignment.provider, model=assignment.model)
                return get_llm_provider()

            async def execute_agent_with_model(agent_name: str, ctx: PipelineContext) -> dict:
                from app.agents.runner import get_agent
                agent_instance = get_agent(agent_name, llm=agent_llm_factory(agent_name))
                return await agent_instance.execute(ctx)

            # Execute question-framing tier first
            tier1_agents = [a for a in agents if a.name == "question-framing"]
            remaining_agents = [a for a in agents if a.name != "question-framing"]

            if tier1_agents:
                context = await execute_pipeline(
                    tier1_agents, context, execute_agent_with_model, on_progress,
                )

            # Apply Agent Gate
            gating_decision = None
            bypass_gating = force_full_analysis or plan == "validate_only"

            if remaining_agents and not bypass_gating:
                remaining_agents, gating_decision = await _apply_gating_and_filter(
                    context, agents, remaining_agents, plan, pipeline_id, db,
                )

            if remaining_agents:
                context = await execute_pipeline(
                    remaining_agents, context, execute_agent_with_model, on_progress,
                )

            # Store results and finalize
            from app.services.result_builder import build_and_store_results
            await build_and_store_results(db, pipeline_id, context)
            await _finalize_pipeline(db, pipeline, pipeline_id, context, agents, gating_decision)

        except (PipelineError, Exception) as e:
            await _handle_pipeline_failure(db, pipeline, pipeline_id, e)


async def _apply_agent_gate(
    context,
    all_agents: list,
    plan: str,
    pipeline_id_str: str,
) -> "GatingDecision | None":
    """Invoke the Agent Gate with a 5-second timeout.

    Returns the GatingDecision on success, or None on failure/timeout
    (falling back to dispatching all agents).
    """
    from app.orchestration.agent_gate import AgentGate, GatingDecision

    framing_output = context.get_agent_output("question-framing")
    available_agents = [a.name for a in all_agents if a.name != "question-framing"]

    try:
        gate = AgentGate()
        decision = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, gate.evaluate, framing_output, available_agents, plan,
            ),
            timeout=5.0,
        )
        logger.info(
            "Agent Gate decision for pipeline %s: %s/%s — dispatching %d of %d agents",
            pipeline_id_str,
            decision.intent.value,
            decision.complexity.value,
            len(decision.dispatched_agents),
            len(available_agents),
        )
        return decision

    except asyncio.TimeoutError:
        logger.error(
            "Agent Gate timed out (>5s) for pipeline %s. "
            "Falling back to all agents.",
            pipeline_id_str,
        )
        return None

    except Exception as exc:
        logger.error(
            "Agent Gate failed for pipeline %s: %s. "
            "Falling back to all agents.",
            pipeline_id_str,
            exc,
        )
        return None


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
