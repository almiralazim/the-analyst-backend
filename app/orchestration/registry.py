"""Load agent definitions from registry.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.orchestration.dag_resolver import AgentNode

_VALID_TIERS = {"premium", "standard", "fast"}


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


def get_agent_tiers(registry_path: str | Path | None = None) -> dict[str, str]:
    """Load model_tier assignments from the registry YAML.

    Returns:
        Mapping of agent_name -> model_tier (defaults to "standard").
    """
    if registry_path is None:
        registry_path = Path(__file__).parent / "registry.yaml"

    path = Path(registry_path)
    if not path.exists():
        raise FileNotFoundError(f"Agent registry not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    tiers: dict[str, str] = {}
    for entry in data.get("agents", []):
        if entry.get("pipeline_step") is None:
            continue
        tier = entry.get("model_tier", "standard")
        if tier not in _VALID_TIERS:
            raise ValueError(
                f"Invalid model_tier '{tier}' for agent '{entry['name']}'. "
                f"Must be one of: {', '.join(sorted(_VALID_TIERS))}"
            )
        tiers[entry["name"]] = tier

    return tiers
