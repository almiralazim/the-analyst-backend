"""Abstract base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    raw_response: dict = field(default_factory=dict)

    @property
    def estimated_cost(self) -> float:
        """Rough cost estimate in USD. Override per provider for accuracy."""
        return (self.input_tokens * 0.003 + self.output_tokens * 0.015) / 1000


class LLMProvider(ABC):
    """Abstract interface for LLM providers.

    All providers implement the same interface so agents are provider-agnostic.
    """

    provider_name: str

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send a completion request and return a standardized response."""
        ...

    @abstractmethod
    async def complete_json(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Request structured JSON output from the model."""
        ...
