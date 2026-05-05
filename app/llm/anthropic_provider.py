"""Anthropic (Claude) LLM provider."""

from __future__ import annotations

import anthropic

from app.config import settings
from app.llm.base import LLMProvider, LLMResponse
from app.llm.retry import llm_retry


class AnthropicProvider(LLMProvider):
    provider_name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)

    @llm_retry()
    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or "You are an expert data analyst.",
            messages=[{"role": "user", "content": prompt}],
        )
        return LLMResponse(
            content=message.content[0].text,
            model=self.model,
            provider=self.provider_name,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            total_tokens=message.usage.input_tokens + message.usage.output_tokens,
            finish_reason=message.stop_reason or "",
            raw_response=message.model_dump(),
        )

    @llm_retry()
    async def complete_json(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        json_system = (system or "You are an expert data analyst.") + (
            "\n\nRespond ONLY with valid JSON. No markdown, no explanation, no code fences."
        )
        return await self.complete(prompt, system=json_system, max_tokens=max_tokens, temperature=temperature)
