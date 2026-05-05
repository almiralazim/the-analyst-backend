"""Tests for the pipeline executor."""

import asyncio
import uuid

import pytest

from app.orchestration.context import PipelineContext
from app.orchestration.dag_resolver import AgentNode
from app.orchestration.executor import PipelineError, execute_pipeline


def _simple_agents() -> list[AgentNode]:
    return [
        AgentNode(name="agent-a", depends_on=[]),
        AgentNode(name="agent-b", depends_on=["agent-a"]),
    ]


class TestPipelineExecutor:
    @pytest.mark.asyncio
    async def test_executes_agents_in_order(self):
        execution_order = []

        async def mock_executor(agent_name: str, context: PipelineContext) -> dict:
            execution_order.append(agent_name)
            return {"output": {"raw_text": f"Result from {agent_name}"}}

        context = PipelineContext(question="test")
        await execute_pipeline(_simple_agents(), context, mock_executor)

        assert execution_order == ["agent-a", "agent-b"]

    @pytest.mark.asyncio
    async def test_stores_agent_outputs_in_context(self):
        async def mock_executor(agent_name: str, context: PipelineContext) -> dict:
            return {"output": {"value": agent_name}}

        context = PipelineContext(question="test")
        result = await execute_pipeline(_simple_agents(), context, mock_executor)

        assert "agent-a" in result.agent_outputs
        assert "agent-b" in result.agent_outputs

    @pytest.mark.asyncio
    async def test_critical_failure_halts_pipeline(self):
        call_count = 0

        async def failing_executor(agent_name: str, context: PipelineContext) -> dict:
            nonlocal call_count
            call_count += 1
            if agent_name == "agent-a":
                raise RuntimeError("Agent A exploded")
            return {"output": {}}

        agents = [
            AgentNode(name="agent-a", is_critical=True, depends_on=[]),
            AgentNode(name="agent-b", depends_on=["agent-a"]),
        ]
        context = PipelineContext(question="test")

        with pytest.raises(PipelineError, match="agent-a"):
            await execute_pipeline(agents, context, failing_executor)

        assert call_count == 1  # agent-b never ran

    @pytest.mark.asyncio
    async def test_non_critical_failure_continues(self):
        execution_order = []

        async def partial_fail_executor(agent_name: str, context: PipelineContext) -> dict:
            execution_order.append(agent_name)
            if agent_name == "agent-a":
                raise RuntimeError("Non-critical failure")
            return {"output": {}}

        agents = [
            AgentNode(name="agent-a", is_critical=False, depends_on=[]),
            AgentNode(name="agent-b", depends_on=[]),  # parallel with agent-a, no dep
        ]
        context = PipelineContext(question="test")

        await execute_pipeline(agents, context, partial_fail_executor)
        assert "agent-b" in execution_order

    @pytest.mark.asyncio
    async def test_progress_events_emitted(self):
        events = []

        async def mock_executor(agent_name: str, context: PipelineContext) -> dict:
            return {"output": {}}

        async def capture_progress(event: dict):
            events.append(event)

        context = PipelineContext(question="test")
        await execute_pipeline(_simple_agents(), context, mock_executor, on_progress=capture_progress)

        event_types = [e["event"] for e in events]
        assert "pipeline_started" in event_types
        assert "tier_started" in event_types
        assert "agent_started" in event_types
        assert "agent_completed" in event_types
        assert "tier_completed" in event_types

    @pytest.mark.asyncio
    async def test_parallel_agents_in_same_tier(self):
        execution_order = []

        async def mock_executor(agent_name: str, context: PipelineContext) -> dict:
            execution_order.append(agent_name)
            return {"output": {}}

        agents = [
            AgentNode(name="parallel-a", depends_on=[]),
            AgentNode(name="parallel-b", depends_on=[]),
            AgentNode(name="after", depends_on=["parallel-a", "parallel-b"]),
        ]
        context = PipelineContext(question="test")
        await execute_pipeline(agents, context, mock_executor)

        # Both parallel agents should run before "after"
        idx_a = execution_order.index("parallel-a")
        idx_b = execution_order.index("parallel-b")
        idx_after = execution_order.index("after")
        assert idx_a < idx_after
        assert idx_b < idx_after


class TestPipelineTimeouts:
    """Tests for pipeline-level and agent-level timeout enforcement."""

    @pytest.mark.asyncio
    async def test_pipeline_timeout_raises_pipeline_error(self):
        """A pipeline that exceeds its timeout raises PipelineError."""
        async def slow_executor(agent_name: str, context: PipelineContext) -> dict:
            await asyncio.sleep(5)
            return {"output": {}}

        agents = [AgentNode(name="slow-agent", depends_on=[])]
        context = PipelineContext(question="test")

        with pytest.raises(PipelineError, match="Pipeline timed out"):
            await execute_pipeline(
                agents, context, slow_executor, pipeline_timeout=0.1,
            )

    @pytest.mark.asyncio
    async def test_pipeline_timeout_emits_pipeline_failed_event(self):
        """On pipeline timeout, a pipeline_failed event is emitted."""
        events = []

        async def slow_executor(agent_name: str, context: PipelineContext) -> dict:
            await asyncio.sleep(5)
            return {"output": {}}

        async def capture_progress(event: dict):
            events.append(event)

        agents = [AgentNode(name="slow-agent", depends_on=[])]
        context = PipelineContext(question="test")

        with pytest.raises(PipelineError):
            await execute_pipeline(
                agents, context, slow_executor,
                on_progress=capture_progress,
                pipeline_timeout=0.1,
            )

        event_types = [e["event"] for e in events]
        assert "pipeline_failed" in event_types
        failed_event = next(e for e in events if e["event"] == "pipeline_failed")
        assert "timed out" in failed_event["error"].lower()

    @pytest.mark.asyncio
    async def test_agent_timeout_critical_raises_pipeline_error(self):
        """A critical agent that times out raises PipelineError."""
        async def slow_executor(agent_name: str, context: PipelineContext) -> dict:
            await asyncio.sleep(5)
            return {"output": {}}

        agents = [
            AgentNode(name="slow-critical", is_critical=True, timeout_seconds=0.1),
        ]
        context = PipelineContext(question="test")

        with pytest.raises(PipelineError, match="slow-critical"):
            await execute_pipeline(
                agents, context, slow_executor, pipeline_timeout=10,
            )

    @pytest.mark.asyncio
    async def test_agent_timeout_emits_agent_failed_event(self):
        """On agent timeout, an agent_failed event is emitted."""
        events = []

        async def slow_executor(agent_name: str, context: PipelineContext) -> dict:
            await asyncio.sleep(5)
            return {"output": {}}

        async def capture_progress(event: dict):
            events.append(event)

        agents = [
            AgentNode(name="slow-agent", is_critical=True, timeout_seconds=0.1),
        ]
        context = PipelineContext(question="test")

        with pytest.raises(PipelineError):
            await execute_pipeline(
                agents, context, slow_executor,
                on_progress=capture_progress,
                pipeline_timeout=10,
            )

        failed_events = [e for e in events if e["event"] == "agent_failed"]
        assert len(failed_events) == 1
        assert failed_events[0]["agent"] == "slow-agent"
        assert "timed out" in failed_events[0]["error"].lower()

    @pytest.mark.asyncio
    async def test_agent_timeout_non_critical_continues(self):
        """A non-critical agent that times out does not halt the pipeline."""
        execution_order = []

        async def mixed_executor(agent_name: str, context: PipelineContext) -> dict:
            execution_order.append(agent_name)
            if agent_name == "slow-optional":
                await asyncio.sleep(5)
            return {"output": {"value": agent_name}}

        agents = [
            AgentNode(name="slow-optional", is_critical=False, timeout_seconds=0.1),
            AgentNode(name="fast-agent", is_critical=True, depends_on=[]),
        ]
        context = PipelineContext(question="test")

        result = await execute_pipeline(
            agents, context, mixed_executor, pipeline_timeout=10,
        )

        # fast-agent should have completed successfully
        assert "fast-agent" in result.agent_outputs

    @pytest.mark.asyncio
    async def test_fast_pipeline_completes_within_timeout(self):
        """A pipeline that finishes quickly completes normally."""
        async def fast_executor(agent_name: str, context: PipelineContext) -> dict:
            return {"output": {"value": agent_name}}

        agents = [
            AgentNode(name="agent-a", depends_on=[]),
            AgentNode(name="agent-b", depends_on=["agent-a"]),
        ]
        context = PipelineContext(question="test")

        result = await execute_pipeline(
            agents, context, fast_executor, pipeline_timeout=10,
        )

        assert "agent-a" in result.agent_outputs
        assert "agent-b" in result.agent_outputs
