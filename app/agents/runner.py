"""Agent runner: maps agent names to implementations and executes them."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.llm import get_llm_provider
from app.orchestration.context import PipelineContext

logger = logging.getLogger(__name__)

# Registry of agent name -> agent class
# Agents register themselves by being imported
_AGENT_REGISTRY: dict[str, type[BaseAgent]] = {}


def register_agent(cls: type[BaseAgent]) -> type[BaseAgent]:
    """Decorator to register an agent class."""
    _AGENT_REGISTRY[cls.name] = cls
    return cls


def get_agent(name: str) -> BaseAgent:
    """Get an agent instance by name."""
    if name not in _AGENT_REGISTRY:
        logger.warning("No specific implementation for agent '%s', using generic", name)
        return GenericAgent(agent_name=name)
    return _AGENT_REGISTRY[name]()


async def execute_agent(agent_name: str, context: PipelineContext) -> dict:
    """Execute a named agent with the given context."""
    agent = get_agent(agent_name)
    return await agent.execute(context)


class GenericAgent(BaseAgent):
    """Fallback agent for agents without a specific implementation.

    Uses the prompt template if available, otherwise builds a generic prompt.
    """
    name = "generic"
    prompt_template = ""

    def __init__(self, agent_name: str = "generic", **kwargs):
        super().__init__(**kwargs)
        self.name = agent_name
        self.prompt_template = f"{agent_name}.md"
        self.system_prompt = (
            f"You are the {agent_name} agent in an analytical pipeline. "
            "Analyze the data and provide structured findings."
        )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "QUESTION": context.question,
            "QUESTION_BRIEF": context.agent_outputs.get("question-framing", {}).get("output", {}).get("raw_text", context.question),
            "DATASET_NAME": context.schema_profile.get("tables", [{}])[0].get("name", "dataset") if context.schema_profile else "dataset",
            "SCHEMA": _format_schema(context.schema_profile),
            "CORRECTIONS": context.format_corrections_for_prompt(),
            "PREVIOUS_RESULTS": _format_previous_results(context),
        }


def _format_schema(profile: dict) -> str:
    """Format schema profile as a readable string for prompts."""
    if not profile:
        return "No schema available."

    lines = []
    for table in profile.get("tables", []):
        lines.append(f"\nTable: {table['name']} ({table.get('row_count', '?')} rows)")
        for col in table.get("columns", []):
            null_info = f", {col.get('null_rate', 0):.0%} null" if col.get("null_rate", 0) > 0 else ""
            lines.append(f"  - {col['name']}: {col.get('type', 'UNKNOWN')}{null_info}")
    return "\n".join(lines)


def _format_previous_results(context: PipelineContext) -> str:
    """Format outputs from previously completed agents."""
    if not context.agent_outputs:
        return "No previous agent results available."

    lines = []
    for agent_name, output in context.agent_outputs.items():
        text = output.get("output", {}).get("raw_text", "")
        if text:
            lines.append(f"\n--- {agent_name} output ---\n{text[:2000]}")
    return "\n".join(lines) if lines else "No previous agent results available."


# Import all agent implementations to trigger registration
def _register_all_agents():
    """Import agent modules to register them."""
    try:
        from app.agents import implementations  # noqa: F401
    except ImportError:
        logger.debug("No agent implementations module found, using generic agents")


_register_all_agents()
