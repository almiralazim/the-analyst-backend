"""DAG resolver: topological sort and tier computation using Kahn's algorithm."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AgentNode:
    """A node in the execution DAG."""
    name: str
    is_critical: bool = True
    depends_on: list[str] = field(default_factory=list)
    depends_on_any: list[str] = field(default_factory=list)
    tier: int = -1
    timeout_seconds: int = 300


def resolve_tiers(agents: list[AgentNode]) -> list[list[AgentNode]]:
    """Compute execution tiers using Kahn's algorithm (topological sort).

    Returns a list of tiers, where each tier is a list of agents
    that can execute in parallel.

    Raises:
        ValueError: If the graph contains cycles or references missing agents.
    """
    agent_map = {a.name: a for a in agents}

    # Validate dependencies exist
    for agent in agents:
        for dep in agent.depends_on:
            if dep not in agent_map:
                raise ValueError(f"Agent '{agent.name}' depends on unknown agent '{dep}'")
        for dep in agent.depends_on_any:
            if dep not in agent_map:
                raise ValueError(f"Agent '{agent.name}' has depends_on_any referencing unknown agent '{dep}'")

    # Build adjacency list and in-degree count
    in_degree: dict[str, int] = defaultdict(int)
    dependents: dict[str, list[str]] = defaultdict(list)

    for agent in agents:
        if agent.name not in in_degree:
            in_degree[agent.name] = 0
        for dep in agent.depends_on:
            in_degree[agent.name] += 1
            dependents[dep].append(agent.name)

    # Kahn's algorithm
    queue: deque[str] = deque()
    for name, degree in in_degree.items():
        if degree == 0:
            queue.append(name)

    tiers: list[list[AgentNode]] = []
    processed = 0

    while queue:
        # All agents in the current queue form one tier
        tier_agents = []
        next_queue: deque[str] = deque()

        while queue:
            name = queue.popleft()
            agent = agent_map[name]
            agent.tier = len(tiers)
            tier_agents.append(agent)
            processed += 1

            # Reduce in-degree for dependents
            for dependent_name in dependents[name]:
                in_degree[dependent_name] -= 1
                if in_degree[dependent_name] == 0:
                    next_queue.append(dependent_name)

        tiers.append(tier_agents)
        queue = next_queue

    if processed != len(agents):
        unprocessed = [a.name for a in agents if a.tier == -1]
        raise ValueError(f"Cycle detected in agent dependencies. Unresolved agents: {unprocessed}")

    return tiers


def filter_agents_by_plan(agents: list[AgentNode], plan: str) -> list[AgentNode]:
    """Filter agents based on the execution plan.

    Plans:
        deep_dive: Tiers 0-6 (analysis agents only, no presentation)
        full_presentation: All agents
        validate_only: Just the validation agent
    """
    if plan == "full_presentation":
        return agents

    if plan == "validate_only":
        return [a for a in agents if a.name == "validation"]

    if plan == "deep_dive":
        # Include the 10 MVP agents
        mvp_agents = {
            "question-framing", "hypothesis", "data-explorer",
            "source-tieout", "descriptive-analytics", "overtime-trend",
            "root-cause-investigator", "validation", "chart-maker",
            "storytelling",
        }
        return [a for a in agents if a.name in mvp_agents]

    return agents


def resolve_gated_dependencies(
    dispatched: set[str],
    all_agents: list[AgentNode],
) -> set[str]:
    """Ensure all dependencies of dispatched agents are also dispatched.

    Walks the DAG and re-includes any gated agent that is a transitive
    dependency of a dispatched agent. Re-included agents will naturally
    appear in earlier tiers when resolve_tiers is called on the final set.

    Args:
        dispatched: Set of agent names currently selected for dispatch.
        all_agents: Full list of AgentNode objects from the registry.

    Returns:
        Expanded set of agent names with all transitive dependencies
        included.
    """
    agent_map = {a.name: a for a in all_agents}
    result = set(dispatched)

    # BFS from each dispatched agent, collecting all transitive deps
    queue: deque[str] = deque(
        name for name in dispatched if name in agent_map
    )
    visited: set[str] = set(queue)

    while queue:
        current = queue.popleft()
        agent = agent_map.get(current)
        if agent is None:
            continue

        for dep in agent.depends_on:
            if dep not in agent_map:
                continue
            if dep not in result:
                logger.info(
                    "Auto-including gated dependency '%s' "
                    "(required by '%s')",
                    dep,
                    current,
                )
                result.add(dep)
            if dep not in visited:
                visited.add(dep)
                queue.append(dep)

    return result
