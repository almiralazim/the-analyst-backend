"""Base agent class that all pipeline agents inherit from."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from app.llm import LLMProvider, LLMResponse, get_llm_provider
from app.llm.prompt_renderer import render_prompt
from app.orchestration.context import PipelineContext

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


class BaseAgent(ABC):
    """Abstract base class for all pipeline agents.

    Each agent has:
    - A name matching the registry entry
    - A prompt template (markdown file)
    - A system prompt defining its role
    - Helper methods it calls after LLM response
    """

    name: str
    prompt_template: str  # Filename in agents/prompts/
    system_prompt: str = "You are an expert data analyst."
    is_critical: bool = True
    timeout_seconds: int = 300

    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm or get_llm_provider()

    async def execute(self, context: PipelineContext) -> dict:
        """Full agent execution: render prompt → call LLM → parse → run helpers."""
        # Build prompt context
        prompt_context = self.build_prompt_context(context)

        # Render prompt template
        template_path = PROMPTS_DIR / self.prompt_template
        if template_path.exists():
            prompt = render_prompt(template_path, prompt_context)
        else:
            prompt = self.build_fallback_prompt(context)

        # Inject corrections
        corrections_text = context.format_corrections_for_prompt()
        prompt = f"{prompt}\n\n{corrections_text}"

        # Call LLM
        logger.info("Agent %s calling LLM (%s)", self.name, self.llm.provider_name)
        response = await self.llm.complete(prompt, system=self.system_prompt)
        logger.info(
            "Agent %s LLM response: %d tokens in, %d tokens out",
            self.name, response.input_tokens, response.output_tokens,
        )

        # Parse response
        parsed = self.parse_response(response)

        # Run helper modules
        enriched = await self.run_helpers(parsed, context)

        return {
            "agent": self.name,
            "output": enriched,
            "llm_usage": {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "model": response.model,
                "provider": response.provider,
            },
        }

    @abstractmethod
    def build_prompt_context(self, context: PipelineContext) -> dict:
        """Build the variable substitution context for the prompt template."""
        ...

    def build_fallback_prompt(self, context: PipelineContext) -> str:
        """Fallback prompt when no template file exists."""
        return f"Analyze the following question about the dataset:\n\nQuestion: {context.question}"

    def parse_response(self, response: LLMResponse) -> dict:
        """Parse the LLM response into structured data.

        Default implementation tries JSON parsing, falls back to raw text.
        """
        content = response.content.strip()

        # Try to extract JSON from markdown code fences
        if "```json" in content:
            start = content.index("```json") + 7
            end = content.index("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.index("```") + 3
            end = content.index("```", start)
            content = content[start:end].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"raw_text": response.content, "parsed": False}

    async def run_helpers(self, parsed: dict, context: PipelineContext) -> dict:
        """Run helper modules on the parsed LLM output.

        Override in subclasses to call specific helpers (chart generation,
        validation, SQL execution, etc.).
        """
        return parsed
