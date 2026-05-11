"""Model router: resolves LLM provider/model assignments for pipeline agents."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.llm.model_registry import ModelRegistry

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when no LLM providers are available."""


@dataclass
class ModelAssignment:
    """Resolved model assignment for a single agent."""

    agent_name: str
    provider: str
    model: str


# Tier-to-provider priority: ordered list of preferred providers per tier.
TIER_PRIORITIES: dict[str, list[str]] = {
    "premium": ["anthropic", "openai", "gemini", "groq"],
    "standard": ["gemini", "openai", "anthropic", "groq"],
    "fast": ["groq", "anthropic", "openai", "gemini"],
}


class ModelRouter:
    """Routes agents to LLM providers based on selection mode and tier config."""

    def __init__(self, registry: ModelRegistry | None = None):
        self.registry = registry or ModelRegistry()

    def resolve_assignments(
        self,
        agent_names: list[str],
        model_selection: str,
        agent_tiers: dict[str, str],
    ) -> list[ModelAssignment]:
        """Resolve model assignments for all agents.

        Args:
            agent_names: Names of agents to assign models to.
            model_selection: User's selection ("auto", provider name, or model ID).
            agent_tiers: Mapping of agent_name -> model_tier from registry.

        Returns:
            List of ModelAssignment objects.

        Raises:
            ConfigurationError: If no providers are available.
        """
        if model_selection == "auto":
            return self._resolve_auto(agent_names, agent_tiers)

        # Check if it's a provider name
        if model_selection in self.registry.all_provider_names:
            return self._resolve_provider(agent_names, model_selection)

        # Must be a model ID
        return self._resolve_model_id(agent_names, model_selection)

    def _resolve_auto(
        self,
        agent_names: list[str],
        agent_tiers: dict[str, str],
    ) -> list[ModelAssignment]:
        """Auto mode: select per-agent based on tier priority with fallback."""
        available = self.registry.get_available_providers()
        if not available:
            raise ConfigurationError(
                "No LLM providers configured. Set at least one API key."
            )

        available_names = {p.name for p in available}
        assignments = []

        for name in agent_names:
            tier = agent_tiers.get(name, "standard")
            provider_name = self._pick_provider_for_tier(
                tier, available_names
            )
            model = self.registry.get_default_model(provider_name)
            assignments.append(ModelAssignment(
                agent_name=name,
                provider=provider_name,
                model=model.id if model else "",
            ))

        return assignments

    def _resolve_provider(
        self,
        agent_names: list[str],
        provider: str,
    ) -> list[ModelAssignment]:
        """Provider mode: use that provider's default model for all agents."""
        model = self.registry.get_default_model(provider)
        model_id = model.id if model else ""
        return [
            ModelAssignment(agent_name=name, provider=provider, model=model_id)
            for name in agent_names
        ]

    def _resolve_model_id(
        self,
        agent_names: list[str],
        model_id: str,
    ) -> list[ModelAssignment]:
        """Model ID mode: use that exact model for all agents."""
        provider = self.registry.get_provider_for_model(model_id) or ""
        return [
            ModelAssignment(agent_name=name, provider=provider, model=model_id)
            for name in agent_names
        ]

    def _pick_provider_for_tier(
        self,
        tier: str,
        available: set[str],
    ) -> str:
        """Pick the best available provider for a given tier.

        Walks the tier priority list. Falls back to any available provider
        if none of the preferred ones are available.
        """
        priorities = TIER_PRIORITIES.get(tier, TIER_PRIORITIES["standard"])
        for provider in priorities:
            if provider in available:
                return provider

        # Fallback: any available provider
        logger.warning(
            "No preferred provider available for tier '%s', "
            "falling back to any available provider",
            tier,
        )
        return next(iter(available))
