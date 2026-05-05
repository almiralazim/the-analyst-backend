"""Tests for the DAG resolver — topological sort and tier computation."""

from __future__ import annotations

import pytest

from app.orchestration.dag_resolver import AgentNode, filter_agents_by_plan, resolve_tiers


def _make_agents() -> list[AgentNode]:
    """Create the MVP 10-agent pipeline for testing."""
    return [
        AgentNode(name="question-framing", depends_on=[]),
        AgentNode(name="data-explorer", depends_on=[]),
        AgentNode(name="hypothesis", depends_on=["question-framing"]),
        AgentNode(name="source-tieout", depends_on=["data-explorer"]),
        AgentNode(name="descriptive-analytics", depends_on=["source-tieout"]),
        AgentNode(name="overtime-trend", depends_on=["source-tieout"]),
        AgentNode(name="root-cause-investigator", depends_on=["descriptive-analytics"]),
        AgentNode(name="validation", depends_on=["root-cause-investigator"]),
        AgentNode(name="chart-maker", depends_on=["validation"]),
        AgentNode(name="storytelling", depends_on=["chart-maker"]),
    ]


class TestResolveTiers:
    def test_produces_correct_number_of_tiers(self):
        agents = _make_agents()
        tiers = resolve_tiers(agents)
        assert len(tiers) == 7

    def test_tier_0_has_no_dependencies(self):
        agents = _make_agents()
        tiers = resolve_tiers(agents)
        tier_0_names = {a.name for a in tiers[0]}
        assert tier_0_names == {"question-framing", "data-explorer"}

    def test_parallel_agents_in_same_tier(self):
        agents = _make_agents()
        tiers = resolve_tiers(agents)
        # Tier 1: hypothesis and source-tieout run in parallel
        tier_1_names = {a.name for a in tiers[1]}
        assert tier_1_names == {"hypothesis", "source-tieout"}
        # Tier 2: descriptive-analytics and overtime-trend run in parallel
        tier_2_names = {a.name for a in tiers[2]}
        assert tier_2_names == {"descriptive-analytics", "overtime-trend"}

    def test_storytelling_is_last(self):
        agents = _make_agents()
        tiers = resolve_tiers(agents)
        last_tier_names = {a.name for a in tiers[-1]}
        assert "storytelling" in last_tier_names

    def test_agents_get_tier_assigned(self):
        agents = _make_agents()
        tiers = resolve_tiers(agents)
        for tier_idx, tier_agents in enumerate(tiers):
            for agent in tier_agents:
                assert agent.tier == tier_idx

    def test_all_agents_processed(self):
        agents = _make_agents()
        tiers = resolve_tiers(agents)
        all_names = {a.name for tier in tiers for a in tier}
        expected = {a.name for a in agents}
        assert all_names == expected


class TestCycleDetection:
    def test_raises_on_cycle(self):
        agents = [
            AgentNode(name="a", depends_on=["b"]),
            AgentNode(name="b", depends_on=["a"]),
        ]
        with pytest.raises(ValueError, match="Cycle detected"):
            resolve_tiers(agents)

    def test_raises_on_missing_dependency(self):
        agents = [
            AgentNode(name="a", depends_on=["nonexistent"]),
        ]
        with pytest.raises(ValueError, match="unknown agent"):
            resolve_tiers(agents)


class TestFilterByPlan:
    def test_deep_dive_returns_10_agents(self):
        agents = _make_agents()
        filtered = filter_agents_by_plan(agents, "deep_dive")
        assert len(filtered) == 10

    def test_validate_only_returns_validation(self):
        agents = _make_agents()
        filtered = filter_agents_by_plan(agents, "validate_only")
        assert len(filtered) == 1
        assert filtered[0].name == "validation"

    def test_full_presentation_returns_all(self):
        agents = _make_agents()
        filtered = filter_agents_by_plan(agents, "full_presentation")
        assert len(filtered) == len(agents)
