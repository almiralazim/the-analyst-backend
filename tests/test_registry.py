"""Tests for the agent registry loader."""

from __future__ import annotations

from app.orchestration.registry import load_registry


class TestLoadRegistry:
    def test_loads_mvp_agents(self):
        agents = load_registry()
        assert len(agents) == 10

    def test_agent_names_match_expected(self):
        agents = load_registry()
        names = {a.name for a in agents}
        expected = {
            "question-framing", "data-explorer", "hypothesis", "source-tieout",
            "descriptive-analytics", "overtime-trend", "root-cause-investigator",
            "validation", "chart-maker", "storytelling",
        }
        assert names == expected

    def test_all_dependencies_are_valid(self):
        agents = load_registry()
        names = {a.name for a in agents}
        for agent in agents:
            for dep in agent.depends_on:
                assert dep in names, f"Agent '{agent.name}' depends on unknown '{dep}'"

    def test_root_agents_have_no_dependencies(self):
        agents = load_registry()
        roots = [a for a in agents if not a.depends_on]
        root_names = {a.name for a in roots}
        assert root_names == {"question-framing", "data-explorer"}
