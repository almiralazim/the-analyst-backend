"""Load and validate the agent relevance map from YAML configuration."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from app.orchestration.agent_gate import ComplexityLevel, IntentCategory

logger = logging.getLogger(__name__)

# The full set of known agents in the pipeline registry.
KNOWN_AGENTS: frozenset[str] = frozenset(
    {
        "question-framing",
        "data-explorer",
        "descriptive-analytics",
        "hypothesis",
        "overtime-trend",
        "root-cause-investigator",
        "source-tieout",
        "chart-maker",
        "storytelling",
        "validation",
    }
)

# Agents that must always be present in every relevance map entry.
MANDATORY_AGENTS: frozenset[str] = frozenset({"data-explorer", "storytelling"})

# Type alias for the relevance map structure.
RelevanceMap = dict[tuple[IntentCategory, ComplexityLevel], set[str]]


def _build_default_map() -> RelevanceMap:
    """Build a hardcoded default map that dispatches all agents for every combination."""
    result: RelevanceMap = {}
    for intent in IntentCategory:
        for complexity in ComplexityLevel:
            result[(intent, complexity)] = set(KNOWN_AGENTS)
    return result


def _expand_rule_entry(
    entry: object,
    mandatory: set[str],
    all_agents: set[str],
    intent: str,
    complexity: str,
) -> set[str]:
    """Expand a single rule entry into a set of agent names.

    Handles the "all" keyword by expanding to the full agent set.
    Adds mandatory agents to every entry.
    """
    if entry == "all":
        return set(all_agents)

    if isinstance(entry, list):
        agents = {str(a) for a in entry}
        agents.update(mandatory)
        return agents

    logger.warning(
        "Unexpected rule entry type for %s/%s: %s. Using all agents.",
        intent,
        complexity,
        type(entry).__name__,
    )
    return set(all_agents)


def _load_yaml(path: Path) -> dict | None:
    """Load and validate YAML file, returning parsed dict or None on failure."""
    if not path.exists():
        logger.error(
            "Agent relevance map not found at %s. Using default (all agents).", path
        )
        return None

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as exc:
        logger.error(
            "Failed to parse agent relevance map at %s: %s. Using default (all agents).",
            path,
            exc,
        )
        return None

    if not isinstance(data, dict):
        logger.error(
            "Agent relevance map is not a valid mapping. Using default (all agents)."
        )
        return None

    return data


def _resolve_agents_for_entry(
    intent_rules: dict,
    intent: IntentCategory,
    complexity: ComplexityLevel,
    mandatory: set[str],
    all_agents: set[str],
) -> set[str]:
    """Resolve the agent set for a single (intent, complexity) pair."""
    entry = intent_rules.get(complexity.value)
    if entry is None:
        return set(all_agents)

    agents = _expand_rule_entry(
        entry, mandatory, all_agents, intent.value, complexity.value
    )

    unknown = agents - all_agents
    for agent_name in sorted(unknown):
        logger.warning(
            "Unknown agent '%s' in relevance map for %s/%s. Ignoring.",
            agent_name,
            intent.value,
            complexity.value,
        )

    agents = (agents & all_agents) | (mandatory & all_agents)
    return agents


def _build_map_from_rules(
    rules: dict, mandatory: set[str], all_agents: set[str]
) -> RelevanceMap:
    """Build the relevance map from parsed rules."""
    relevance_map: RelevanceMap = {}

    for intent in IntentCategory:
        intent_rules = rules.get(intent.value)
        if not isinstance(intent_rules, dict):
            for complexity in ComplexityLevel:
                relevance_map[(intent, complexity)] = set(all_agents)
            continue

        for complexity in ComplexityLevel:
            relevance_map[(intent, complexity)] = _resolve_agents_for_entry(
                intent_rules, intent, complexity, mandatory, all_agents
            )

    # Final validation: ensure mandatory agents are present.
    for key, agents in relevance_map.items():
        missing = (mandatory & all_agents) - agents
        if missing:
            logger.warning(
                "Mandatory agents %s missing for %s/%s. Adding them.",
                sorted(missing),
                key[0].value,
                key[1].value,
            )
            agents.update(missing)

    return relevance_map


def load_relevance_map(path: Path | None = None) -> RelevanceMap:
    """Load the agent relevance map from YAML.

    Returns a mapping of (IntentCategory, ComplexityLevel) -> set of agent names.
    Falls back to a hardcoded default map (all agents) if YAML is missing or unparseable.

    Args:
        path: Path to the YAML config file. Defaults to the bundled
              agent_relevance.yaml alongside this module.
    """
    if path is None:
        path = Path(__file__).parent / "agent_relevance.yaml"

    data = _load_yaml(Path(path))
    if data is None:
        return _build_default_map()

    yaml_mandatory = data.get("mandatory_agents")
    mandatory = (
        {str(a) for a in yaml_mandatory}
        if isinstance(yaml_mandatory, list)
        else set(MANDATORY_AGENTS)
    )

    rules = data.get("rules")
    if not isinstance(rules, dict):
        logger.error(
            "Agent relevance map has no valid 'rules' section. Using default (all agents)."
        )
        return _build_default_map()

    return _build_map_from_rules(rules, mandatory, set(KNOWN_AGENTS))
