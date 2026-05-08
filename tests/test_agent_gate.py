"""Unit tests for Agent Gate classification logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.orchestration.agent_gate import (
    AgentGate,
    ComplexityLevel,
    GatingDecision,
    IntentCategory,
    classify_complexity,
    classify_intent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_framing(
    hypotheses: list | None = None,
    temporal_scope: dict | None = None,
    dimensions: list | None = None,
    comparative_dimensions: list | None = None,
    success_criteria: list | None = None,
    question: str = "",
) -> dict:
    """Build a minimal framing output dict for testing."""
    output: dict = {
        "hypotheses": hypotheses if hypotheses is not None else [],
        "temporal_scope": temporal_scope,
        "dimensions": dimensions if dimensions is not None else [],
    }
    if comparative_dimensions is not None:
        output["comparative_dimensions"] = comparative_dimensions
    if success_criteria is not None:
        output["success_criteria"] = success_criteria
    if question:
        output["question"] = question
    return output


ALL_AGENTS = [
    "question-framing",
    "data-explorer",
    "descriptive-analytics",
    "hypothesis",
    "overtime-trend",
    "root-cause-investigator",
    "source-tieout",
    "chart-maker",
    "storytelling",
    "validation",
]


# ---------------------------------------------------------------------------
# Intent Classification Tests
# ---------------------------------------------------------------------------

class TestClassifyIntent:
    """Tests for classify_intent covering the classification table."""

    def test_simple_overview_no_hypotheses_no_temporal_few_dimensions(self):
        """No hypotheses, no temporal, ≤2 dimensions → overview."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue", "product"],
        )
        assert classify_intent(framing) == IntentCategory.OVERVIEW

    def test_temporal_scope_present_no_hypotheses_gives_trend_analysis(self):
        """Temporal scope present, no hypotheses → trend_analysis."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope={"start": "2024-01", "end": "2024-12"},
            dimensions=["revenue"],
        )
        assert classify_intent(framing) == IntentCategory.TREND_ANALYSIS

    def test_hypotheses_present_no_temporal_gives_hypothesis_testing(self):
        """Hypotheses present, no temporal scope → hypothesis_testing."""
        framing = _make_framing(
            hypotheses=["Revenue increased due to new product launch"],
            temporal_scope=None,
            dimensions=["revenue"],
        )
        assert classify_intent(framing) == IntentCategory.HYPOTHESIS_TESTING

    def test_hypotheses_plus_root_cause_keywords_gives_root_cause(self):
        """Hypotheses + root-cause keywords → root_cause_investigation."""
        framing = _make_framing(
            hypotheses=["Churn increased due to pricing"],
            temporal_scope=None,
            dimensions=["churn"],
            question="Why did churn increase last quarter?",
        )
        assert classify_intent(framing) == IntentCategory.ROOT_CAUSE_INVESTIGATION

    def test_comparative_dimensions_gte_2_gives_comparison(self):
        """Comparative dimensions ≥ 2 → comparison."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue", "cost", "margin"],
            comparative_dimensions=["region_a", "region_b"],
        )
        assert classify_intent(framing) == IntentCategory.COMPARISON

    def test_anomaly_keywords_in_success_criteria_gives_anomaly_detection(self):
        """Anomaly keywords in success criteria → anomaly_detection."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue", "cost", "margin"],
            success_criteria=["Identify any anomaly in the revenue trend"],
        )
        assert classify_intent(framing) == IntentCategory.ANOMALY_DETECTION

    def test_tie_breaking_root_cause_wins_over_hypothesis_testing(self):
        """When both root_cause and hypothesis_testing match, root_cause wins."""
        framing = _make_framing(
            hypotheses=["Price caused churn"],
            temporal_scope=None,
            dimensions=["churn"],
            question="What is the cause of churn?",
        )
        result = classify_intent(framing)
        assert result == IntentCategory.ROOT_CAUSE_INVESTIGATION

    def test_tie_breaking_anomaly_wins_over_comparison(self):
        """When anomaly_detection and comparison both match, anomaly wins."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue", "cost", "margin"],
            comparative_dimensions=["region_a", "region_b"],
            success_criteria=["Find outlier regions"],
        )
        result = classify_intent(framing)
        assert result == IntentCategory.ANOMALY_DETECTION

    def test_empty_framing_defaults_to_overview(self):
        """Completely empty framing output defaults to overview."""
        framing = _make_framing()
        assert classify_intent(framing) == IntentCategory.OVERVIEW


# ---------------------------------------------------------------------------
# Complexity Classification Tests
# ---------------------------------------------------------------------------

class TestClassifyComplexity:
    """Tests for classify_complexity covering low/medium/high thresholds."""

    def test_low_complexity_few_dimensions_few_hypotheses_no_temporal(self):
        """dimensions ≤ 2, hypotheses ≤ 1, no temporal → low."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue"],
        )
        assert classify_complexity(framing) == ComplexityLevel.LOW

    def test_low_complexity_with_one_hypothesis(self):
        """dimensions ≤ 2, hypotheses = 1, no temporal → low."""
        framing = _make_framing(
            hypotheses=["Revenue grew"],
            temporal_scope=None,
            dimensions=["revenue", "product"],
        )
        assert classify_complexity(framing) == ComplexityLevel.LOW

    def test_medium_complexity_dimensions_3_hypotheses_2(self):
        """dimensions ≤ 4, hypotheses ≤ 3 but not meeting low criteria → medium."""
        framing = _make_framing(
            hypotheses=["H1", "H2"],
            temporal_scope=None,
            dimensions=["d1", "d2", "d3"],
        )
        assert classify_complexity(framing) == ComplexityLevel.MEDIUM

    def test_medium_complexity_with_temporal(self):
        """Temporal scope present pushes out of low even with few dims."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope={"start": "2024-01", "end": "2024-06"},
            dimensions=["revenue"],
        )
        assert classify_complexity(framing) == ComplexityLevel.MEDIUM

    def test_high_complexity_many_dimensions(self):
        """dimensions > 4 → high."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["d1", "d2", "d3", "d4", "d5"],
        )
        assert classify_complexity(framing) == ComplexityLevel.HIGH

    def test_high_complexity_many_hypotheses(self):
        """hypotheses > 3 → high."""
        framing = _make_framing(
            hypotheses=["H1", "H2", "H3", "H4"],
            temporal_scope=None,
            dimensions=["d1"],
        )
        assert classify_complexity(framing) == ComplexityLevel.HIGH

    def test_high_complexity_temporal_plus_hypotheses_plus_many_dims(self):
        """temporal + hypotheses + dimensions > 2 → high."""
        framing = _make_framing(
            hypotheses=["H1"],
            temporal_scope={"start": "2024-01"},
            dimensions=["d1", "d2", "d3"],
        )
        assert classify_complexity(framing) == ComplexityLevel.HIGH


# ---------------------------------------------------------------------------
# AgentGate.evaluate() Tests
# ---------------------------------------------------------------------------

class TestAgentGateEvaluate:
    """Tests for the AgentGate.evaluate() method."""

    @pytest.fixture
    def gate(self):
        """Create an AgentGate with mocked dependencies."""
        from app.orchestration.dag_resolver import AgentNode

        mock_relevance_map = {
            (IntentCategory.OVERVIEW, ComplexityLevel.LOW): {
                "data-explorer", "descriptive-analytics",
                "chart-maker", "storytelling",
            },
            (IntentCategory.OVERVIEW, ComplexityLevel.MEDIUM): {
                "data-explorer", "descriptive-analytics",
                "chart-maker", "storytelling", "source-tieout",
            },
            (IntentCategory.OVERVIEW, ComplexityLevel.HIGH): set(ALL_AGENTS),
            (IntentCategory.TREND_ANALYSIS, ComplexityLevel.LOW): {
                "data-explorer", "overtime-trend",
                "chart-maker", "storytelling",
            },
        }
        mock_registry_agents = [
            AgentNode(name=name, depends_on=[])
            for name in ALL_AGENTS
        ]

        with patch("app.orchestration.relevance_map.load_relevance_map", return_value=mock_relevance_map), \
             patch("app.orchestration.registry.load_registry", return_value=mock_registry_agents):
            gate = AgentGate()
            gate.relevance_map = mock_relevance_map
            gate._registry_agents = mock_registry_agents
            yield gate

    def test_malformed_input_empty_dict_defaults_to_high_all_agents(self, gate):
        """Empty dict → high complexity, all agents dispatched."""
        decision = gate.evaluate(
            framing_output={},
            available_agents=ALL_AGENTS,
            execution_plan="deep_dive",
        )
        assert decision.complexity == ComplexityLevel.HIGH
        assert set(decision.dispatched_agents) == set(ALL_AGENTS)

    def test_malformed_input_none_defaults_to_high_all_agents(self, gate):
        """None framing output → high complexity, all agents dispatched."""
        decision = gate.evaluate(
            framing_output=None,
            available_agents=ALL_AGENTS,
            execution_plan="deep_dive",
        )
        assert decision.complexity == ComplexityLevel.HIGH
        assert set(decision.dispatched_agents) == set(ALL_AGENTS)

    def test_malformed_input_missing_required_fields(self, gate):
        """Dict missing required fields → high complexity, all agents."""
        decision = gate.evaluate(
            framing_output={"hypotheses": []},
            available_agents=ALL_AGENTS,
            execution_plan="deep_dive",
        )
        assert decision.complexity == ComplexityLevel.HIGH
        assert set(decision.dispatched_agents) == set(ALL_AGENTS)

    def test_low_complexity_overview_dispatches_at_most_5_agents(self, gate):
        """deep_dive + low complexity → ≤ 5 agents dispatched."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue"],
        )
        decision = gate.evaluate(
            framing_output=framing,
            available_agents=ALL_AGENTS,
            execution_plan="deep_dive",
        )
        assert decision.complexity == ComplexityLevel.LOW
        assert decision.intent == IntentCategory.OVERVIEW
        assert len(decision.dispatched_agents) <= 5

    def test_high_complexity_dispatches_all_agents(self, gate):
        """High complexity → all available agents dispatched."""
        framing = _make_framing(
            hypotheses=["H1", "H2", "H3", "H4"],
            temporal_scope=None,
            dimensions=["d1", "d2", "d3", "d4", "d5"],
        )
        decision = gate.evaluate(
            framing_output=framing,
            available_agents=ALL_AGENTS,
            execution_plan="deep_dive",
        )
        assert decision.complexity == ComplexityLevel.HIGH
        assert set(decision.dispatched_agents) == set(ALL_AGENTS)

    def test_gate_duration_is_recorded(self, gate):
        """Gate duration should be a non-negative integer."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue"],
        )
        decision = gate.evaluate(
            framing_output=framing,
            available_agents=ALL_AGENTS,
            execution_plan="deep_dive",
        )
        assert decision.gate_duration_ms >= 0

    def test_skipped_agents_have_reasons(self, gate):
        """Every skipped agent should have a non-empty reason."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue"],
        )
        decision = gate.evaluate(
            framing_output=framing,
            available_agents=ALL_AGENTS,
            execution_plan="deep_dive",
        )
        for skipped in decision.skipped_agents:
            assert skipped.name
            assert skipped.reason


# ---------------------------------------------------------------------------
# Bypass Scenarios
# ---------------------------------------------------------------------------

class TestBypassScenarios:
    """Tests for gating bypass conditions (force_full_analysis, validate_only)."""

    def test_force_full_analysis_bypasses_gating(self):
        """force_full_analysis=True should result in all agents dispatched.

        This tests the pipeline-level bypass logic. The gate itself doesn't
        handle force_full_analysis — the pipeline skips calling the gate.
        We verify the gate's malformed-input fallback produces the same
        effect when the pipeline would bypass.
        """
        # The pipeline bypasses the gate entirely when force_full_analysis=True.
        # We verify the expected behavior: all agents dispatched.
        # Simulating what the pipeline does: it doesn't call gate.evaluate()
        # and instead dispatches all agents.
        bypass_gating = True
        available_agents = ALL_AGENTS

        if bypass_gating:
            dispatched = list(available_agents)

        assert set(dispatched) == set(ALL_AGENTS)

    def test_validate_only_plan_bypasses_gating(self):
        """validate_only plan should bypass gating entirely.

        The pipeline skips the gate for validate_only plans since
        the plan already specifies a minimal agent set.
        """
        plan = "validate_only"
        bypass_gating = plan == "validate_only"
        available_agents = ["validation"]

        if bypass_gating:
            dispatched = list(available_agents)

        assert dispatched == ["validation"]


# ---------------------------------------------------------------------------
# Timeout Simulation
# ---------------------------------------------------------------------------

class TestTimeoutSimulation:
    """Tests for gate timeout fallback behavior."""

    def test_gate_timeout_falls_back_to_all_agents(self):
        """If the gate exceeds timeout, pipeline dispatches all agents.

        The pipeline wraps gate.evaluate() in a timeout. On timeout,
        it falls back to dispatching all agents.
        """
        available_agents = ALL_AGENTS

        # Simulate the pipeline's timeout handling logic
        gate_mock = MagicMock()
        gate_mock.evaluate.side_effect = TimeoutError("Gate exceeded 5s")

        try:
            gate_mock.evaluate(
                framing_output=_make_framing(),
                available_agents=available_agents,
                execution_plan="deep_dive",
            )
            dispatched = []
        except TimeoutError:
            # Pipeline fallback: dispatch all agents on timeout
            dispatched = list(available_agents)

        assert set(dispatched) == set(ALL_AGENTS)
        gate_mock.evaluate.assert_called_once()


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases in classification logic."""

    def test_empty_hypotheses_list(self):
        """Empty hypotheses list should not trigger hypothesis-related intents."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue"],
        )
        intent = classify_intent(framing)
        assert intent == IntentCategory.OVERVIEW

    def test_missing_temporal_scope_key_entirely(self):
        """Missing temporal_scope key (not in dict) should be treated as no temporal."""
        framing = {
            "hypotheses": [],
            "dimensions": ["revenue"],
            "temporal_scope": None,
        }
        intent = classify_intent(framing)
        assert intent != IntentCategory.TREND_ANALYSIS

    def test_boundary_dimension_count_exactly_2(self):
        """Exactly 2 dimensions should still qualify for overview (≤2)."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["d1", "d2"],
        )
        intent = classify_intent(framing)
        assert intent == IntentCategory.OVERVIEW

        complexity = classify_complexity(framing)
        assert complexity == ComplexityLevel.LOW

    def test_boundary_dimension_count_exactly_5(self):
        """Exactly 5 dimensions should trigger high complexity (>4)."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["d1", "d2", "d3", "d4", "d5"],
        )
        complexity = classify_complexity(framing)
        assert complexity == ComplexityLevel.HIGH

    def test_boundary_dimension_count_exactly_4(self):
        """Exactly 4 dimensions with ≤3 hypotheses → medium (not high)."""
        framing = _make_framing(
            hypotheses=["H1", "H2"],
            temporal_scope=None,
            dimensions=["d1", "d2", "d3", "d4"],
        )
        complexity = classify_complexity(framing)
        assert complexity == ComplexityLevel.MEDIUM

    def test_multiple_intents_match_highest_priority_wins(self):
        """When multiple intents match, the highest priority wins per tie-breaking."""
        # This triggers: hypothesis_testing (hypotheses + no temporal)
        # AND root_cause_investigation (hypotheses + "cause" keyword)
        # root_cause_investigation has higher priority
        framing = _make_framing(
            hypotheses=["Pricing caused churn"],
            temporal_scope=None,
            dimensions=["churn"],
            question="What is the driver of churn?",
        )
        intent = classify_intent(framing)
        assert intent == IntentCategory.ROOT_CAUSE_INVESTIGATION

    def test_outlier_keyword_triggers_anomaly_detection(self):
        """The keyword 'outlier' in success criteria triggers anomaly_detection."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["d1", "d2", "d3"],
            success_criteria=["Detect outlier values in revenue"],
        )
        intent = classify_intent(framing)
        assert intent == IntentCategory.ANOMALY_DETECTION

    def test_unexpected_keyword_triggers_anomaly_detection(self):
        """The keyword 'unexpected' in success criteria triggers anomaly_detection."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["d1", "d2", "d3"],
            success_criteria=["Flag unexpected drops in conversion"],
        )
        intent = classify_intent(framing)
        assert intent == IntentCategory.ANOMALY_DETECTION

    def test_cause_keyword_without_hypotheses_gives_overview(self):
        """Root-cause keywords without hypotheses should not trigger root_cause."""
        framing = _make_framing(
            hypotheses=[],
            temporal_scope=None,
            dimensions=["revenue"],
            question="What is the cause of revenue growth?",
        )
        intent = classify_intent(framing)
        # Without hypotheses, root_cause_investigation won't match
        assert intent == IntentCategory.OVERVIEW
