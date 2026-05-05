"""LLM provider factory. Instantiates the configured provider."""

from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.llm.base import LLMProvider


@lru_cache(maxsize=4)
def get_llm_provider(provider_name: str | None = None) -> LLMProvider:
    """Return an LLM provider instance.

    Args:
        provider_name: One of 'anthropic', 'openai', 'gemini', 'groq'.
                       Defaults to settings.llm_default_provider.
    """
    name = provider_name or settings.llm_default_provider

    if name == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    elif name == "openai":
        from app.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif name == "gemini":
        from app.llm.gemini_provider import GeminiProvider
        return GeminiProvider()
    elif name == "groq":
        from app.llm.groq_provider import GroqProvider
        return GroqProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider: {name}. "
            f"Supported: anthropic, openai, gemini, groq"
        )
