"""Tests for the LLM provider factory."""

from __future__ import annotations

import pytest

from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider


class TestLLMFactory:
    def test_returns_anthropic_provider(self):
        pytest.importorskip("anthropic")
        get_llm_provider.cache_clear()
        provider = get_llm_provider("anthropic")
        assert isinstance(provider, LLMProvider)
        assert provider.provider_name == "anthropic"

    def test_returns_openai_provider(self):
        pytest.importorskip("openai")
        get_llm_provider.cache_clear()
        provider = get_llm_provider("openai")
        assert isinstance(provider, LLMProvider)
        assert provider.provider_name == "openai"

    def test_returns_gemini_provider(self):
        pytest.importorskip("google.genai")
        get_llm_provider.cache_clear()
        provider = get_llm_provider("gemini")
        assert isinstance(provider, LLMProvider)
        assert provider.provider_name == "gemini"

    def test_returns_groq_provider(self):
        pytest.importorskip("groq")
        get_llm_provider.cache_clear()
        provider = get_llm_provider("groq")
        assert isinstance(provider, LLMProvider)
        assert provider.provider_name == "groq"

    def test_raises_on_unknown_provider(self):
        get_llm_provider.cache_clear()
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm_provider("unknown_provider")
