"""Google Gemini LLM provider."""

from __future__ import annotations

from google import genai
from google.genai import types

from app.config import settings
from app.llm.base import LLMProvider, LLMResponse
from app.llm.retry import llm_retry


class GeminiProvider(LLMProvider):
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self.client = genai.Client(api_key=self.api_key)

    @llm_retry()
    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=system or "You are an expert data analyst.",
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        usage = response.usage_metadata
        return LLMResponse(
            content=response.text or "",
            model=self.model,
            provider=self.provider_name,
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
            total_tokens=usage.total_token_count if usage else 0,
            finish_reason=str(response.candidates[0].finish_reason) if response.candidates else "",
        )

    @llm_retry()
    async def complete_json(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=(system or "You are an expert data analyst.") + " Respond ONLY with valid JSON.",
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type="application/json",
        )
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        usage = response.usage_metadata
        return LLMResponse(
            content=response.text or "",
            model=self.model,
            provider=self.provider_name,
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
            total_tokens=usage.total_token_count if usage else 0,
            finish_reason=str(response.candidates[0].finish_reason) if response.candidates else "",
        )
