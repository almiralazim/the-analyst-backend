"""Tests for the LLM provider factory."""

from __future__ import annotations

import pytest

from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider


class TestLLMFactory:
    def test_returns_anthropic_provider(self):
        pytest.importorskip("anthropic")
        provider = get_llm_provider("anthropic")
        assert isinstance(provider, LLMProvider)
        assert provider.provider_name == "anthropic"

    def test_returns_openai_provider(self):
        pytest.importorskip("openai")
        provider = get_llm_provider("openai")
        assert isinstance(provider, LLMProvider)
        assert provider.provider_name == "openai"

    def test_returns_gemini_provider(self):
        pytest.importorskip("google.genai")
        provider = get_llm_provider("gemini")
        assert isinstance(provider, LLMProvider)
        assert provider.provider_name == "gemini"

    def test_returns_groq_provider(self):
        pytest.importorskip("groq")
        provider = get_llm_provider("groq")
        assert isinstance(provider, LLMProvider)
        assert provider.provider_name == "groq"

    def test_raises_on_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm_provider("unknown_provider")

    def test_model_override(self):
        pytest.importorskip("anthropic")
        provider = get_llm_provider("anthropic", model="claude-haiku")
        assert provider.model == "claude-haiku"

    def test_model_none_uses_default(self):
        pytest.importorskip("anthropic")
        provider = get_llm_provider("anthropic")
        # Should use the settings default
        assert provider.model is not None
        assert len(provider.model) > 0
