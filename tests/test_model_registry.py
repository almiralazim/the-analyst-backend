"""Unit tests for the Model Registry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.llm.model_registry import ModelRegistry


@pytest.fixture
def registry():
    return ModelRegistry()


class TestIsValidSelection:
    """Tests for ModelRegistry.is_valid_selection()."""

    def test_auto_is_valid(self, registry):
        assert registry.is_valid_selection("auto") is True

    def test_known_providers_are_valid(self, registry):
        for name in ["anthropic", "openai", "gemini", "groq"]:
            assert registry.is_valid_selection(name) is True

    def test_known_model_ids_are_valid(self, registry):
        model_ids = [
            "claude-sonnet-4-20250514",
            "claude-haiku",
            "gpt-4o",
            "gpt-4o-mini",
            "gemini-2.5-pro",
            "llama-3.3-70b-versatile",
        ]
        for mid in model_ids:
            assert registry.is_valid_selection(mid) is True

    def test_invalid_strings_are_rejected(self, registry):
        invalid = ["", "unknown", "gpt-5", "claude-opus", "random-model"]
        for val in invalid:
            assert registry.is_valid_selection(val) is False


class TestGetProviderForModel:
    """Tests for ModelRegistry.get_provider_for_model()."""

    def test_anthropic_models(self, registry):
        assert registry.get_provider_for_model("claude-sonnet-4-20250514") == "anthropic"
        assert registry.get_provider_for_model("claude-haiku") == "anthropic"

    def test_openai_models(self, registry):
        assert registry.get_provider_for_model("gpt-4o") == "openai"
        assert registry.get_provider_for_model("gpt-4o-mini") == "openai"

    def test_gemini_models(self, registry):
        assert registry.get_provider_for_model("gemini-2.5-pro") == "gemini"

    def test_groq_models(self, registry):
        assert registry.get_provider_for_model("llama-3.3-70b-versatile") == "groq"

    def test_unknown_model_returns_none(self, registry):
        assert registry.get_provider_for_model("nonexistent") is None


class TestGetAvailableProviders:
    """Tests for ModelRegistry.get_available_providers()."""

    @patch("app.llm.model_registry.settings")
    def test_returns_only_providers_with_keys(self, mock_settings):
        mock_settings.anthropic_api_key = "sk-test"
        mock_settings.openai_api_key = ""
        mock_settings.gemini_api_key = "gem-key"
        mock_settings.groq_api_key = ""

        registry = ModelRegistry()
        available = registry.get_available_providers()
        names = [p.name for p in available]

        assert "anthropic" in names
        assert "gemini" in names
        assert "openai" not in names
        assert "groq" not in names

    @patch("app.llm.model_registry.settings")
    def test_returns_empty_when_no_keys(self, mock_settings):
        mock_settings.anthropic_api_key = ""
        mock_settings.openai_api_key = ""
        mock_settings.gemini_api_key = ""
        mock_settings.groq_api_key = ""

        registry = ModelRegistry()
        available = registry.get_available_providers()
        assert available == []


class TestProviderDefaults:
    """Each provider should have exactly one default model."""

    def test_each_provider_has_one_default(self, registry):
        for provider in registry.get_all_providers():
            defaults = [m for m in provider.models if m.is_default]
            assert len(defaults) == 1, (
                f"Provider '{provider.name}' has {len(defaults)} default models"
            )


class TestIsProviderAvailable:
    """Tests for ModelRegistry.is_provider_available()."""

    @patch("app.llm.model_registry.settings")
    def test_available_when_key_set(self, mock_settings):
        mock_settings.anthropic_api_key = "sk-test"
        registry = ModelRegistry()
        assert registry.is_provider_available("anthropic") is True

    @patch("app.llm.model_registry.settings")
    def test_unavailable_when_key_empty(self, mock_settings):
        mock_settings.anthropic_api_key = ""
        registry = ModelRegistry()
        assert registry.is_provider_available("anthropic") is False

    def test_unknown_provider_unavailable(self, registry):
        assert registry.is_provider_available("unknown_provider") is False
