"""Pipeline execution context — shared state across agents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.helpers.sql_helpers import QueryResult


@dataclass
class PipelineContext:
    """Shared context passed to every agent during pipeline execution."""

    # Identity
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    dataset_id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID = field(default_factory=uuid.uuid4)
    question: str = ""
    execution_plan: str = "deep_dive"

    # Dataset info
    duckdb_path: str = ""
    schema_profile: dict = field(default_factory=dict)

    # Knowledge context (loaded at bootstrap)
    corrections: list[dict] = field(default_factory=list)
    learnings: list[dict] = field(default_factory=list)
    user_preferences: dict = field(default_factory=dict)

    # Agent outputs (populated as agents complete)
    agent_outputs: dict[str, Any] = field(default_factory=dict)

    # Query results (populated by agents during run_helpers)
    query_results: dict[str, list[Any]] = field(default_factory=dict)

    # Accumulated results
    findings: list[dict] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)
    narrative: dict = field(default_factory=dict)
    validation_result: dict = field(default_factory=dict)

    def get_agent_output(self, agent_name: str) -> Any:
        """Get the output of a previously completed agent."""
        return self.agent_outputs.get(agent_name)

    def store_query_result(self, agent_name: str, result: "QueryResult") -> None:
        """Store a query result namespaced by agent name."""
        if agent_name not in self.query_results:
            self.query_results[agent_name] = []
        self.query_results[agent_name].append(result)

    def get_query_results(self, agent_name: str) -> list[Any]:
        """Retrieve query results produced by a specific agent."""
        return self.query_results.get(agent_name, [])

    def format_corrections_for_prompt(self) -> str:
        """Format corrections as a string for injection into agent prompts."""
        if not self.corrections:
            return "No corrections logged for this dataset."

        lines = ["## Known Corrections (DO NOT repeat these mistakes)\n"]
        for c in self.corrections:
            lines.append(f"- [{c.get('severity', 'medium').upper()}] {c.get('description', '')}")
            if c.get("prevention_rule"):
                lines.append(f"  Prevention: {c['prevention_rule']}")
        return "\n".join(lines)
