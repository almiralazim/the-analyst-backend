"""Static registry of LLM providers and models with tier mappings."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class ModelInfo:
    """Metadata for a single model."""

    id: str
    provider: str
    label: str
    description: str
    tier: str
    is_default: bool


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata for a provider and its available models."""

    name: str
    label: str
    models: tuple[ModelInfo, ...]


# Provider/model definitions
_PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo(
        name="anthropic",
        label="Anthropic",
        models=(
            ModelInfo(
                id="claude-sonnet-4-20250514",
                provider="anthropic",
                label="Claude Sonnet 4",
                description="Complex reasoning and analysis",
                tier="premium",
                is_default=True,
            ),
            ModelInfo(
                id="claude-haiku",
                provider="anthropic",
                label="Claude Haiku",
                description="Fast classification and extraction",
                tier="fast",
                is_default=False,
            ),
        ),
    ),
    ProviderInfo(
        name="openai",
        label="OpenAI",
        models=(
            ModelInfo(
                id="gpt-4o",
                provider="openai",
                label="GPT-4o",
                description="Advanced reasoning and generation",
                tier="premium",
                is_default=True,
            ),
            ModelInfo(
                id="gpt-4o-mini",
                provider="openai",
                label="GPT-4o Mini",
                description="Balanced performance and cost",
                tier="standard",
                is_default=False,
            ),
        ),
    ),
    ProviderInfo(
        name="gemini",
        label="Gemini",
        models=(
            ModelInfo(
                id="gemini-2.5-pro",
                provider="gemini",
                label="Gemini 2.5 Pro",
                description="Balanced reasoning and generation",
                tier="standard",
                is_default=True,
            ),
        ),
    ),
    ProviderInfo(
        name="groq",
        label="Groq",
        models=(
            ModelInfo(
                id="llama-3.3-70b-versatile",
                provider="groq",
                label="Llama 3.3 70B",
                description="Ultra-fast inference",
                tier="fast",
                is_default=True,
            ),
        ),
    ),
)

# API key setting names per provider
_API_KEY_SETTINGS: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
}


class ModelRegistry:
    """Static registry of providers and models.

    Checks API key availability at runtime to determine which
    providers are usable.
    """

    def __init__(self) -> None:
        self._providers = _PROVIDERS
        self._model_index: dict[str, ModelInfo] = {}
        self._provider_index: dict[str, ProviderInfo] = {}
        for provider in self._providers:
            self._provider_index[provider.name] = provider
            for model in provider.models:
                self._model_index[model.id] = model

    def get_available_providers(self) -> list[ProviderInfo]:
        """Return providers that have API keys configured."""
        return [
            p for p in self._providers
            if self.is_provider_available(p.name)
        ]

    def get_provider_for_model(self, model_id: str) -> str | None:
        """Map a model identifier to its parent provider name."""
        model = self._model_index.get(model_id)
        return model.provider if model else None

    def is_valid_selection(self, value: str) -> bool:
        """Check if a value is 'auto', a known provider, or a known model ID."""
        if value == "auto":
            return True
        if value in self._provider_index:
            return True
        if value in self._model_index:
            return True
        return False

    def is_provider_available(self, provider: str) -> bool:
        """Check if a provider's API key is configured (non-empty)."""
        attr = _API_KEY_SETTINGS.get(provider)
        if not attr:
            return False
        key = getattr(settings, attr, "")
        return bool(key)

    def get_default_model(self, provider: str) -> ModelInfo | None:
        """Get the default model for a provider."""
        prov = self._provider_index.get(provider)
        if not prov:
            return None
        for model in prov.models:
            if model.is_default:
                return model
        return None

    def get_model(self, model_id: str) -> ModelInfo | None:
        """Get model info by ID."""
        return self._model_index.get(model_id)

    def get_all_providers(self) -> list[ProviderInfo]:
        """Return all known providers regardless of availability."""
        return list(self._providers)

    @property
    def all_provider_names(self) -> list[str]:
        """All known provider names."""
        return [p.name for p in self._providers]

    @property
    def all_model_ids(self) -> list[str]:
        """All known model IDs."""
        return list(self._model_index.keys())
