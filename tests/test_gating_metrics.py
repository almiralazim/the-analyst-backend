"""Tests for gating metrics computation in pipeline result metadata."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock


def _compute_gating_metrics(
    context_agent_outputs: dict,
    agents: list,
    gating_decision,
) -> dict:
    """Extract the gating metrics computation logic for testability.

    This mirrors the logic in _run_pipeline for computing gating_metrics.
    """
    total_input_tokens = 0
    total_output_tokens = 0
    for agent_output in context_agent_outputs.values():
        if isinstance(agent_output, dict):
            usage = agent_output.get("llm_usage", {})
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)

    agents_available_count = len(
        [a for a in agents if a.name != "question-framing"]
    )
    agents_dispatched_count = (
        len(gating_decision.dispatched_agents)
        if gating_decision is not None
        else agents_available_count
    )
    agents_skipped_count = agents_available_count - agents_dispatched_count

    gate_duration_ms = (
        gating_decision.gate_duration_ms
        if gating_decision is not None
        else 0
    )

    avg_tokens_per_agent = 0
    if agents_dispatched_count > 0 and total_input_tokens + total_output_tokens > 0:
        dispatched_agent_count = agents_dispatched_count
        if dispatched_agent_count > 0:
            avg_tokens_per_agent = (
                (total_input_tokens + total_output_tokens) // dispatched_agent_count
            )
    estimated_token_savings = avg_tokens_per_agent * agents_skipped_count

    return {
        "total_token_count": total_input_tokens + total_output_tokens,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "agents_dispatched_count": agents_dispatched_count,
        "agents_available_count": agents_available_count,
        "agents_skipped_count": agents_skipped_count,
        "gate_duration_ms": gate_duration_ms,
        "estimated_token_savings": estimated_token_savings,
    }


@dataclass
class FakeAgent:
    name: str


@dataclass
class FakeGatingDecision:
    dispatched_agents: list[str]
    gate_duration_ms: int


class TestGatingMetrics:
    """Tests for gating metrics computation."""

    def test_total_token_count_sums_all_agents(self):
        """Total token count includes input + output from all agent outputs."""
        agent_outputs = {
            "question-framing": {
                "agent": "question-framing",
                "output": {},
                "llm_usage": {"input_tokens": 500, "output_tokens": 200},
            },
            "data-explorer": {
                "agent": "data-explorer",
                "output": {},
                "llm_usage": {"input_tokens": 1000, "output_tokens": 800},
            },
            "storytelling": {
                "agent": "storytelling",
                "output": {},
                "llm_usage": {"input_tokens": 600, "output_tokens": 400},
            },
        }
        agents = [
            FakeAgent("question-framing"),
            FakeAgent("data-explorer"),
            FakeAgent("storytelling"),
            FakeAgent("hypothesis"),
            FakeAgent("chart-maker"),
        ]
        decision = FakeGatingDecision(
            dispatched_agents=["data-explorer", "storytelling"],
            gate_duration_ms=5,
        )

        metrics = _compute_gating_metrics(agent_outputs, agents, decision)

        assert metrics["total_token_count"] == 3500
        assert metrics["input_tokens"] == 2100
        assert metrics["output_tokens"] == 1400

    def test_agents_dispatched_vs_available(self):
        """Records correct dispatched and available counts."""
        agent_outputs = {}
        agents = [
            FakeAgent("question-framing"),
            FakeAgent("data-explorer"),
            FakeAgent("storytelling"),
            FakeAgent("hypothesis"),
            FakeAgent("chart-maker"),
            FakeAgent("overtime-trend"),
        ]
        decision = FakeGatingDecision(
            dispatched_agents=["data-explorer", "storytelling", "chart-maker"],
            gate_duration_ms=3,
        )

        metrics = _compute_gating_metrics(agent_outputs, agents, decision)

        assert metrics["agents_available_count"] == 5
        assert metrics["agents_dispatched_count"] == 3
        assert metrics["agents_skipped_count"] == 2

    def test_gate_duration_recorded_separately(self):
        """Gate execution time is recorded from the gating decision."""
        agent_outputs = {}
        agents = [FakeAgent("question-framing"), FakeAgent("data-explorer")]
        decision = FakeGatingDecision(
            dispatched_agents=["data-explorer"],
            gate_duration_ms=42,
        )

        metrics = _compute_gating_metrics(agent_outputs, agents, decision)

        assert metrics["gate_duration_ms"] == 42

    def test_estimated_token_savings_based_on_skipped_count(self):
        """Token savings estimated as avg tokens per dispatched agent * skipped count."""
        agent_outputs = {
            "data-explorer": {
                "agent": "data-explorer",
                "output": {},
                "llm_usage": {"input_tokens": 1000, "output_tokens": 500},
            },
            "storytelling": {
                "agent": "storytelling",
                "output": {},
                "llm_usage": {"input_tokens": 800, "output_tokens": 400},
            },
        }
        agents = [
            FakeAgent("question-framing"),
            FakeAgent("data-explorer"),
            FakeAgent("storytelling"),
            FakeAgent("hypothesis"),
            FakeAgent("chart-maker"),
            FakeAgent("overtime-trend"),
        ]
        decision = FakeGatingDecision(
            dispatched_agents=["data-explorer", "storytelling"],
            gate_duration_ms=3,
        )

        metrics = _compute_gating_metrics(agent_outputs, agents, decision)

        # Total tokens = 2700, dispatched = 2, avg = 1350
        # Skipped = 3, savings = 1350 * 3 = 4050
        assert metrics["estimated_token_savings"] == 4050

    def test_no_gating_decision_dispatches_all(self):
        """When gating decision is None, all agents are considered dispatched."""
        agent_outputs = {
            "data-explorer": {
                "agent": "data-explorer",
                "output": {},
                "llm_usage": {"input_tokens": 500, "output_tokens": 300},
            },
        }
        agents = [
            FakeAgent("question-framing"),
            FakeAgent("data-explorer"),
            FakeAgent("storytelling"),
        ]

        metrics = _compute_gating_metrics(agent_outputs, agents, None)

        assert metrics["agents_dispatched_count"] == 2
        assert metrics["agents_available_count"] == 2
        assert metrics["agents_skipped_count"] == 0
        assert metrics["gate_duration_ms"] == 0
        assert metrics["estimated_token_savings"] == 0

    def test_no_tokens_produces_zero_savings(self):
        """When no token data is available, savings estimate is zero."""
        agent_outputs = {}
        agents = [
            FakeAgent("question-framing"),
            FakeAgent("data-explorer"),
            FakeAgent("hypothesis"),
        ]
        decision = FakeGatingDecision(
            dispatched_agents=["data-explorer"],
            gate_duration_ms=2,
        )

        metrics = _compute_gating_metrics(agent_outputs, agents, decision)

        assert metrics["estimated_token_savings"] == 0
        assert metrics["total_token_count"] == 0

    def test_handles_agent_output_without_llm_usage(self):
        """Agent outputs without llm_usage field are handled gracefully."""
        agent_outputs = {
            "data-explorer": {
                "agent": "data-explorer",
                "output": {"some": "data"},
            },
            "storytelling": {
                "agent": "storytelling",
                "output": {},
                "llm_usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }
        agents = [
            FakeAgent("question-framing"),
            FakeAgent("data-explorer"),
            FakeAgent("storytelling"),
        ]
        decision = FakeGatingDecision(
            dispatched_agents=["data-explorer", "storytelling"],
            gate_duration_ms=1,
        )

        metrics = _compute_gating_metrics(agent_outputs, agents, decision)

        assert metrics["total_token_count"] == 150
        assert metrics["input_tokens"] == 100
        assert metrics["output_tokens"] == 50
