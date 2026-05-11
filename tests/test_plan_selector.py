"""Tests for the auto plan selector."""

import pytest

from app.orchestration.plan_selector import auto_select_plan, should_downgrade_to_overview


class TestShouldDowngradeToOverview:
    """Tests for the question classification logic."""

    # --- Should downgrade (simple overview questions) ---

    @pytest.mark.parametrize("question", [
        "tell me about this dataset",
        "Tell me about the data",
        "describe this dataset",
        "Describe the data",
        "summarize the dataset",
        "give me a summary",
        "give me an overview",
        "what is this dataset",
        "what's in this dataset",
        "what does this dataset contain",
        "what does the data look like",
        "show me the dataset",
        "overview of the data",
        "give me a breakdown",
    ])
    def test_overview_phrases_downgrade(self, question):
        assert should_downgrade_to_overview(question) is True

    @pytest.mark.parametrize("question", [
        "what columns are there",
        "what tables exist",
        "how many rows",
        "how many columns",
        "list the columns",
        "list the fields",
        "what's the schema",
        "show me the structure",
        "what's the shape",
    ])
    def test_schema_questions_downgrade(self, question):
        assert should_downgrade_to_overview(question) is True

    @pytest.mark.parametrize("question", [
        "profile this data",
        "explore the dataset",
        "inspect this data",
        "examine the dataset",
    ])
    def test_exploration_phrases_downgrade(self, question):
        assert should_downgrade_to_overview(question) is True

    @pytest.mark.parametrize("question", [
        "hello",
        "what is this",
        "show me",
    ])
    def test_short_simple_questions_downgrade(self, question):
        assert should_downgrade_to_overview(question) is True

    # --- Should NOT downgrade (complex questions) ---

    @pytest.mark.parametrize("question", [
        "why did revenue drop last quarter",
        "what caused the churn increase",
        "what drove the growth in Q4",
        "what explains the decline in conversions",
        "root cause of the revenue drop",
    ])
    def test_root_cause_questions_not_downgraded(self, question):
        assert should_downgrade_to_overview(question) is False

    @pytest.mark.parametrize("question", [
        "how has revenue changed over time",
        "show me the trend in signups",
        "month over month growth",
        "year over year comparison",
        "revenue growth since January",
        "how did sales change from Q1 to Q2",
        "what's the decline in active users",
    ])
    def test_trend_questions_not_downgraded(self, question):
        assert should_downgrade_to_overview(question) is False

    @pytest.mark.parametrize("question", [
        "compare region A vs region B",
        "which segment has the highest revenue",
        "difference between mobile and desktop",
        "which product performs best",
    ])
    def test_comparison_questions_not_downgraded(self, question):
        assert should_downgrade_to_overview(question) is False

    @pytest.mark.parametrize("question", [
        "is there a correlation between price and sales",
        "investigate the drop in conversions",
        "find anomalies in the revenue data",
        "detect outliers in transaction amounts",
        "predict next quarter revenue",
    ])
    def test_analytical_questions_not_downgraded(self, question):
        assert should_downgrade_to_overview(question) is False

    def test_empty_question_not_downgraded(self):
        assert should_downgrade_to_overview("") is False
        assert should_downgrade_to_overview("   ") is False

    def test_very_short_question_not_downgraded(self):
        assert should_downgrade_to_overview("hi") is False


class TestAutoSelectPlan:
    """Tests for the auto_select_plan function."""

    def test_downgrades_deep_dive_for_simple_question(self):
        result = auto_select_plan("tell me about this dataset", "deep_dive")
        assert result == "quick_overview"

    def test_keeps_deep_dive_for_complex_question(self):
        result = auto_select_plan("why did revenue drop last quarter", "deep_dive")
        assert result == "deep_dive"

    def test_never_downgrades_quick_overview(self):
        """Already quick_overview stays quick_overview."""
        result = auto_select_plan("tell me about this dataset", "quick_overview")
        assert result == "quick_overview"

    def test_never_downgrades_full_presentation(self):
        """full_presentation is an explicit choice, never downgraded."""
        result = auto_select_plan("tell me about this dataset", "full_presentation")
        assert result == "full_presentation"

    def test_never_downgrades_validate_only(self):
        """validate_only is an explicit choice, never downgraded."""
        result = auto_select_plan("tell me about this dataset", "validate_only")
        assert result == "validate_only"

    def test_complex_question_with_overview_words_not_downgraded(self):
        """Questions that have overview words but also complex signals stay deep_dive."""
        result = auto_select_plan(
            "describe the trend in revenue over time", "deep_dive"
        )
        assert result == "deep_dive"

    def test_case_insensitive(self):
        result = auto_select_plan("TELL ME ABOUT THIS DATASET", "deep_dive")
        assert result == "quick_overview"
