"""Unit tests for the Model Router."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.llm.model_registry import ModelRegistry, ModelInfo, ProviderInfo
from app.llm.model_router import ModelRouter, ModelAssignment, ConfigurationError


@pytest.fixture
def all_available_registry():
    """Registry where all providers are available."""
    with patch("app.llm.model_registry.settings") as mock_settings:
        mock_settings.anthropic_api_key = "sk-test"
        mock_settings.openai_api_key = "sk-test"
        mock_settings.gemini_api_key = "gem-test"
        mock_settings.groq_api_key = "groq-test"
        registry = ModelRegistry()
        yield registry


@pytest.fixture
def router(all_available_registry):
    return ModelRouter(registry=all_available_registry)


SAMPLE_AGENTS = ["question-framing", "hypothesis", "root-cause-investigator"]
SAMPLE_TIERS = {
    "question-framing": "fast",
    "hypothesis": "standard",
    "root-cause-investigator": "premium",
}


class TestAutoMode:
    """Tests for auto mode routing."""

    def test_assigns_correct_providers_by_tier(self, router):
        assignments = router.resolve_assignments(
            SAMPLE_AGENTS, "auto", SAMPLE_TIERS
        )
        assignment_map = {a.agent_name: a for a in assignments}

        # Fast tier prefers groq
        assert assignment_map["question-framing"].provider == "groq"
        assert assignment_map["question-framing"].model == "llama-3.3-70b-versatile"

        # Standard tier prefers gemini
        assert assignment_map["hypothesis"].provider == "gemini"
        assert assignment_map["hypothesis"].model == "gemini-2.5-pro"

        # Premium tier prefers anthropic
        assert assignment_map["root-cause-investigator"].provider == "anthropic"
        assert assignment_map["root-cause-investigator"].model == "claude-sonnet-4-20250514"

    def test_fallback_when_preferred_unavailable(self):
        """When groq is unavailable, fast tier falls back to anthropic."""
        with patch("app.llm.model_registry.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-test"
            mock_settings.openai_api_key = "sk-test"
            mock_settings.gemini_api_key = "gem-test"
            mock_settings.groq_api_key = ""  # groq unavailable

            registry = ModelRegistry()
            router = ModelRouter(registry=registry)

            assignments = router.resolve_assignments(
                ["question-framing"], "auto", {"question-framing": "fast"}
            )
            # Should fall back to anthropic (2nd in fast priority)
            assert assignments[0].provider == "anthropic"

    def test_fallback_to_any_available(self):
        """When all tier-preferred providers are unavailable, use any available."""
        with patch("app.llm.model_registry.settings") as mock_settings:
            # Only gemini available
            mock_settings.anthropic_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.gemini_api_key = "gem-test"
            mock_settings.groq_api_key = ""

            registry = ModelRegistry()
            router = ModelRouter(registry=registry)

            assignments = router.resolve_assignments(
                ["question-framing"], "auto", {"question-framing": "fast"}
            )
            # Fast priority is groq, anthropic, openai, gemini
            # Only gemini available, so falls back to gemini
            assert assignments[0].provider == "gemini"

    def test_raises_when_no_providers_available(self):
        """ConfigurationError when no providers have API keys."""
        with patch("app.llm.model_registry.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.gemini_api_key = ""
            mock_settings.groq_api_key = ""

            registry = ModelRegistry()
            router = ModelRouter(registry=registry)

            with pytest.raises(ConfigurationError):
                router.resolve_assignments(
                    ["agent1"], "auto", {"agent1": "standard"}
                )

    def test_defaults_to_standard_tier(self, router):
        """Agents without a tier entry default to standard."""
        assignments = router.resolve_assignments(
            ["unknown-agent"], "auto", {}
        )
        # Standard tier prefers gemini
        assert assignments[0].provider == "gemini"


class TestProviderMode:
    """Tests for provider name selection mode."""

    def test_all_agents_get_same_provider(self, router):
        assignments = router.resolve_assignments(
            SAMPLE_AGENTS, "openai", SAMPLE_TIERS
        )
        for a in assignments:
            assert a.provider == "openai"
            assert a.model == "gpt-4o"

    def test_anthropic_provider(self, router):
        assignments = router.resolve_assignments(
            ["agent1"], "anthropic", {"agent1": "fast"}
        )
        assert assignments[0].provider == "anthropic"
        assert assignments[0].model == "claude-sonnet-4-20250514"

    def test_groq_provider(self, router):
        assignments = router.resolve_assignments(
            ["agent1"], "groq", {"agent1": "premium"}
        )
        assert assignments[0].provider == "groq"
        assert assignments[0].model == "llama-3.3-70b-versatile"


class TestModelIdMode:
    """Tests for specific model ID selection mode."""

    def test_all_agents_get_exact_model(self, router):
        assignments = router.resolve_assignments(
            SAMPLE_AGENTS, "gpt-4o-mini", SAMPLE_TIERS
        )
        for a in assignments:
            assert a.provider == "openai"
            assert a.model == "gpt-4o-mini"

    def test_claude_haiku_model(self, router):
        assignments = router.resolve_assignments(
            ["agent1"], "claude-haiku", {"agent1": "standard"}
        )
        assert assignments[0].provider == "anthropic"
        assert assignments[0].model == "claude-haiku"

    def test_gemini_model(self, router):
        assignments = router.resolve_assignments(
            ["agent1"], "gemini-2.5-pro", {"agent1": "fast"}
        )
        assert assignments[0].provider == "gemini"
        assert assignments[0].model == "gemini-2.5-pro"
