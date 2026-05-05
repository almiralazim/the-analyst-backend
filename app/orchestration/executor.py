"""Pipeline executor: runs agents tier-by-tier with progress tracking and timeouts."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from app.config import settings
from app.orchestration.context import PipelineContext
from app.orchestration.dag_resolver import AgentNode, resolve_tiers

logger = logging.getLogger(__name__)

# Type for WebSocket broadcast callback
ProgressCallback = Callable[[dict], Any]


class PipelineError(Exception):
    """Raised when a critical agent fails and the pipeline must halt."""
    def __init__(self, agent_name: str, error: str, tier: int):
        self.agent_name = agent_name
        self.error = error
        self.tier = tier
        super().__init__(f"Critical agent '{agent_name}' failed at tier {tier}: {error}")


async def execute_pipeline(
    agents: list[AgentNode],
    context: PipelineContext,
    agent_executor: Callable,
    on_progress: ProgressCallback | None = None,
    pipeline_timeout: int | None = None,
) -> PipelineContext:
    """Execute a pipeline by running agents tier-by-tier.

    Args:
        agents: List of AgentNode objects (already filtered by plan).
        context: Shared pipeline context.
        agent_executor: Async callable(agent_name, context) -> dict.
        on_progress: Optional callback for WebSocket progress events.
        pipeline_timeout: Max seconds for the entire pipeline. Defaults to
            settings.pipeline_timeout_seconds (600).
    """
    if pipeline_timeout is None:
        pipeline_timeout = settings.pipeline_timeout_seconds

    tiers = resolve_tiers(agents)
    total_agents = sum(len(t) for t in tiers)

    await _emit(on_progress, {
        "event": "pipeline_started",
        "pipeline_id": str(context.run_id),
        "total_agents": total_agents,
        "total_tiers": len(tiers),
        "timestamp": _now(),
    })

    try:
        await asyncio.wait_for(
            _execute_tiers(tiers, context, agent_executor, on_progress),
            timeout=pipeline_timeout,
        )
    except asyncio.TimeoutError:
        await _emit(on_progress, {
            "event": "pipeline_failed",
            "pipeline_id": str(context.run_id),
            "error": "Pipeline timed out",
            "timestamp": _now(),
        })
        raise PipelineError(
            agent_name="pipeline",
            error=f"Pipeline timed out after {pipeline_timeout}s",
            tier=-1,
        )

    return context


async def _execute_tiers(
    tiers: list[list[AgentNode]],
    context: PipelineContext,
    agent_executor: Callable,
    on_progress: ProgressCallback | None,
) -> None:
    """Run all tiers sequentially, agents within a tier concurrently."""
    for tier_idx, tier_agents in enumerate(tiers):
        agent_names = [a.name for a in tier_agents]

        await _emit(on_progress, {
            "event": "tier_started",
            "tier": tier_idx,
            "agents": agent_names,
            "timestamp": _now(),
        })

        tier_start = time.monotonic()

        # Run all agents in this tier concurrently
        tasks = []
        for agent in tier_agents:
            timeout = agent.timeout_seconds or settings.agent_default_timeout_seconds
            tasks.append(
                _run_single_agent(agent, context, agent_executor, on_progress, timeout=timeout)
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for agent, result in zip(tier_agents, results):
            if isinstance(result, PipelineError):
                raise result
            elif isinstance(result, Exception):
                logger.error("Agent %s failed: %s", agent.name, result)
                await _emit(on_progress, {
                    "event": "agent_failed",
                    "agent": agent.name,
                    "tier": tier_idx,
                    "error": str(result),
                    "critical": agent.is_critical,
                    "timestamp": _now(),
                })
                if agent.is_critical:
                    raise PipelineError(agent.name, str(result), tier_idx)
            else:
                context.agent_outputs[agent.name] = result

        tier_duration = int((time.monotonic() - tier_start) * 1000)
        await _emit(on_progress, {
            "event": "tier_completed",
            "tier": tier_idx,
            "duration_ms": tier_duration,
            "timestamp": _now(),
        })


async def _run_single_agent(
    agent: AgentNode,
    context: PipelineContext,
    agent_executor: Callable,
    on_progress: ProgressCallback | None,
    timeout: int = 300,
) -> dict:
    """Run a single agent with timing, progress events, and a per-agent timeout."""
    await _emit(on_progress, {
        "event": "agent_started",
        "agent": agent.name,
        "tier": agent.tier,
        "timestamp": _now(),
    })

    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            agent_executor(agent.name, context),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        await _emit(on_progress, {
            "event": "agent_failed",
            "agent": agent.name,
            "tier": agent.tier,
            "error": "Agent timed out",
            "critical": agent.is_critical,
            "timestamp": _now(),
        })
        if agent.is_critical:
            raise PipelineError(agent.name, "Agent timed out", agent.tier)
        # For non-critical agents, return the exception so the tier loop can handle it
        return {}

    duration_ms = int((time.monotonic() - start) * 1000)

    await _emit(on_progress, {
        "event": "agent_completed",
        "agent": agent.name,
        "tier": agent.tier,
        "duration_ms": duration_ms,
        "timestamp": _now(),
    })

    return result


async def _emit(callback: ProgressCallback | None, event: dict) -> None:
    """Emit a progress event if a callback is registered."""
    if callback:
        try:
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.warning("Progress callback failed for event: %s", event.get("event"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
