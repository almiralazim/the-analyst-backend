"""Load agent definitions from registry.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.orchestration.dag_resolver import AgentNode


def load_registry(registry_path: str | Path | None = None) -> list[AgentNode]:
    """Load agent definitions from a YAML registry file.

    Args:
        registry_path: Path to registry.yaml. Defaults to bundled registry.

    Returns:
        List of AgentNode objects with dependency information.
    """
    if registry_path is None:
        registry_path = Path(__file__).parent / "registry.yaml"

    path = Path(registry_path)
    if not path.exists():
        raise FileNotFoundError(f"Agent registry not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    agents = []
    for entry in data.get("agents", []):
        # Skip standalone agents (no pipeline_step)
        if entry.get("pipeline_step") is None:
            continue

        agents.append(AgentNode(
            name=entry["name"],
            is_critical=entry.get("critical", True),
            depends_on=entry.get("depends_on", []),
            depends_on_any=entry.get("depends_on_any", []),
        ))

    return agents
