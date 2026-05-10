"""Agent Gate: rule-based intent and complexity classification for dynamic agent dispatch."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class IntentCategory(str, Enum):
    """Primary intent categories for question classification."""

    OVERVIEW = "overview"
    TREND_ANALYSIS = "trend_analysis"
    HYPOTHESIS_TESTING = "hypothesis_testing"
    ROOT_CAUSE_INVESTIGATION = "root_cause_investigation"
    COMPARISON = "comparison"
    ANOMALY_DETECTION = "anomaly_detection"


class ComplexityLevel(str, Enum):
    """Complexity levels based on analytical dimensions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class SkippedAgent:
    """An agent excluded from dispatch by the gate."""

    name: str
    tier: int | None
    reason: str


@dataclass
class GatingDecision:
    """The output of the Agent Gate evaluation."""

    intent: IntentCategory
    complexity: ComplexityLevel
    dispatched_agents: list[str] = field(default_factory=list)
    skipped_agents: list[SkippedAgent] = field(default_factory=list)
    gate_duration_ms: int = 0
    reasoning: str = ""


# Priority order for tie-breaking when multiple intent signals match.
# Higher index = higher priority.
_INTENT_PRIORITY: list[IntentCategory] = [
    IntentCategory.OVERVIEW,
    IntentCategory.TREND_ANALYSIS,
    IntentCategory.COMPARISON,
    IntentCategory.ANOMALY_DETECTION,
    IntentCategory.HYPOTHESIS_TESTING,
    IntentCategory.ROOT_CAUSE_INVESTIGATION,
]

_ROOT_CAUSE_KEYWORDS = {"why", "cause", "driver"}
_ANOMALY_KEYWORDS = {"anomaly", "outlier", "unexpected"}


def _extract_hypotheses(framing_output: dict) -> list[Any]:
    """Safely extract hypotheses list from framing output."""
    hypotheses = framing_output.get("hypotheses")
    if isinstance(hypotheses, list):
        return hypotheses
    return []


def _extract_dimensions(framing_output: dict) -> list[Any]:
    """Safely extract dimensions from framing output.

    Maps from the actual schema: sub_questions act as analytical dimensions.
    Falls back to the legacy 'dimensions' key if present.
    """
    # Try legacy key first
    dimensions = framing_output.get("dimensions")
    if isinstance(dimensions, list):
        return dimensions
    # Derive from sub_questions (each is an analytical dimension)
    sub_questions = framing_output.get("sub_questions")
    if isinstance(sub_questions, list):
        return sub_questions
    return []


def _extract_comparative_dimensions(framing_output: dict) -> list[Any]:
    """Safely extract comparative dimensions from framing output.

    Derives from sub_questions with analysis_type 'comparison'.
    Falls back to the legacy 'comparative_dimensions' key.
    """
    # Try legacy key first
    comparative = framing_output.get("comparative_dimensions")
    if isinstance(comparative, list):
        return comparative
    # Derive from sub_questions with comparison type
    sub_questions = framing_output.get("sub_questions")
    if isinstance(sub_questions, list):
        return [
            sq for sq in sub_questions
            if isinstance(sq, dict) and sq.get("analysis_type") == "comparison"
        ]
    return []


def _has_temporal_from_legacy(temporal: Any) -> bool:
    """Check if the legacy temporal_scope value indicates a temporal scope."""
    if isinstance(temporal, dict) and len(temporal) > 0:
        return True
    return isinstance(temporal, str) and bool(temporal)


def _has_temporal_from_sub_questions(sub_questions: list[Any]) -> bool:
    """Check if any sub_question has analysis_type 'trend'."""
    return any(
        isinstance(sq, dict) and sq.get("analysis_type") == "trend"
        for sq in sub_questions
    )


def _has_temporal_scope(framing_output: dict) -> bool:
    """Check if temporal scope is present.

    Checks the legacy 'temporal_scope' key, or derives from sub_questions
    that have analysis_type 'trend' or mention time-related terms.
    """
    temporal = framing_output.get("temporal_scope")
    if temporal is not None and _has_temporal_from_legacy(temporal):
        return True

    sub_questions = framing_output.get("sub_questions")
    if isinstance(sub_questions, list):
        return _has_temporal_from_sub_questions(sub_questions)
    return False


def _extract_success_criteria(framing_output: dict) -> list[str]:
    """Safely extract success_criteria as a list of strings."""
    criteria = framing_output.get("success_criteria")
    if isinstance(criteria, list):
        return [str(c) for c in criteria]
    return []


def _has_anomaly_keywords(success_criteria: list[str]) -> bool:
    """Check if any success criteria contain anomaly-related keywords."""
    for criterion in success_criteria:
        lower = criterion.lower()
        if any(kw in lower for kw in _ANOMALY_KEYWORDS):
            return True
    return False


def _has_root_cause_keywords(framing_output: dict) -> bool:
    """Check for root-cause keywords in the question or success criteria."""
    question = str(framing_output.get("question", "")).lower()
    success_criteria = _extract_success_criteria(framing_output)
    all_text = question + " " + " ".join(success_criteria)
    return any(kw in all_text for kw in _ROOT_CAUSE_KEYWORDS)


def classify_intent(framing_output: dict) -> IntentCategory:
    """Classify the primary intent from question-framing output using rule-based pattern matching.

    Uses the classification table from the design document with tie-breaking
    priority: root_cause_investigation > hypothesis_testing > anomaly_detection >
    comparison > trend_analysis > overview.
    """
    hypotheses = _extract_hypotheses(framing_output)
    dimensions = _extract_dimensions(framing_output)
    comparative_dims = _extract_comparative_dimensions(framing_output)
    temporal = _has_temporal_scope(framing_output)
    success_criteria = _extract_success_criteria(framing_output)

    has_hypotheses = len(hypotheses) > 0
    has_root_cause_kw = _has_root_cause_keywords(framing_output)
    has_anomaly_kw = _has_anomaly_keywords(success_criteria)
    has_comparative = len(comparative_dims) >= 2

    # Collect all matching intents
    matched: list[IntentCategory] = []

    # Hypotheses present + root-cause keywords → root_cause_investigation
    if has_hypotheses and has_root_cause_kw:
        matched.append(IntentCategory.ROOT_CAUSE_INVESTIGATION)

    # Hypotheses present, no temporal scope → hypothesis_testing
    if has_hypotheses and not temporal:
        matched.append(IntentCategory.HYPOTHESIS_TESTING)

    # Anomaly keywords in success criteria → anomaly_detection
    if has_anomaly_kw:
        matched.append(IntentCategory.ANOMALY_DETECTION)

    # Comparative dimensions ≥ 2 → comparison
    if has_comparative:
        matched.append(IntentCategory.COMPARISON)

    # Temporal scope present, no hypotheses → trend_analysis
    if temporal and not has_hypotheses:
        matched.append(IntentCategory.TREND_ANALYSIS)

    # No hypotheses, no temporal scope, ≤2 dimensions → overview
    if not has_hypotheses and not temporal and len(dimensions) <= 2:
        matched.append(IntentCategory.OVERVIEW)

    # If nothing matched, default to overview
    if not matched:
        return IntentCategory.OVERVIEW

    # Tie-breaking: return the highest-priority match
    best = matched[0]
    best_priority = _INTENT_PRIORITY.index(best)
    for intent in matched[1:]:
        priority = _INTENT_PRIORITY.index(intent)
        if priority > best_priority:
            best = intent
            best_priority = priority

    return best


def classify_complexity(framing_output: dict) -> ComplexityLevel:
    """Classify complexity level from question-framing output.

    Rules:
    - low: dimensions ≤ 2 AND hypotheses ≤ 1 AND no temporal scope
    - medium: dimensions ≤ 4 AND hypotheses ≤ 3
    - high: dimensions > 4 OR hypotheses > 3 OR (temporal + hypotheses + dimensions > 2)
    """
    dimensions = _extract_dimensions(framing_output)
    hypotheses = _extract_hypotheses(framing_output)
    temporal = _has_temporal_scope(framing_output)

    dim_count = len(dimensions)
    hyp_count = len(hypotheses)

    # Check high complexity first (most specific conditions)
    if dim_count > 4:
        return ComplexityLevel.HIGH
    if hyp_count > 3:
        return ComplexityLevel.HIGH
    # "temporal + hypotheses + dimensions > 2" means all three are present
    # and the combined signal count exceeds 2
    temporal_val = 1 if temporal else 0
    hyp_val = 1 if hyp_count > 0 else 0
    dim_val = 1 if dim_count > 2 else 0
    if (temporal_val + hyp_val + dim_val) > 2:
        return ComplexityLevel.HIGH

    # Check low complexity
    if dim_count <= 2 and hyp_count <= 1 and not temporal:
        return ComplexityLevel.LOW

    # Default to medium
    return ComplexityLevel.MEDIUM


def _is_valid_framing_output(framing_output: Any) -> bool:
    """Check if framing_output is a well-formed dict with usable fields.

    Accepts both the legacy schema (hypotheses, dimensions, temporal_scope)
    and the actual schema (hypotheses, sub_questions, recommended_complexity).
    """
    if not isinstance(framing_output, dict):
        return False

    # Must have at least one of the key signal sources
    has_hypotheses_key = "hypotheses" in framing_output
    has_sub_questions_key = "sub_questions" in framing_output
    has_dimensions_key = "dimensions" in framing_output

    if not (has_hypotheses_key or has_sub_questions_key or has_dimensions_key):
        return False

    # Validate types if present
    hypotheses = framing_output.get("hypotheses")
    if hypotheses is not None and not isinstance(hypotheses, list):
        return False

    sub_questions = framing_output.get("sub_questions")
    if sub_questions is not None and not isinstance(sub_questions, list):
        return False

    dimensions = framing_output.get("dimensions")
    if dimensions is not None and not isinstance(dimensions, list):
        return False

    return True


# Agents that are always included when question-framing has already run.
_ALWAYS_INCLUDED_AGENT = "question-framing"


class AgentGate:
    """Rule-based gate that determines which agents to dispatch based on framing output."""

    def __init__(
        self,
        relevance_map_path: Path | None = None,
        registry_path: Path | None = None,
    ):
        from app.orchestration.registry import load_registry
        from app.orchestration.relevance_map import load_relevance_map

        self.relevance_map = load_relevance_map(relevance_map_path)
        self._registry_agents = load_registry(registry_path)

    def evaluate(
        self,
        framing_output: Any,
        available_agents: list[str],
        execution_plan: str,
    ) -> GatingDecision:
        """Classify intent/complexity and produce a gating decision.

        Args:
            framing_output: The structured output from the question-framing agent.
            available_agents: List of agent names available in the current plan.
            execution_plan: One of "deep_dive", "full_presentation", "validate_only".

        Returns:
            A GatingDecision with dispatched/skipped agents and reasoning.
        """
        start_ns = time.perf_counter_ns()

        # Handle malformed input: default to high complexity, dispatch all agents
        if not _is_valid_framing_output(framing_output):
            logger.warning(
                "Malformed framing output received. "
                "Defaulting to high complexity with all agents."
            )
            duration_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
            return GatingDecision(
                intent=IntentCategory.OVERVIEW,
                complexity=ComplexityLevel.HIGH,
                dispatched_agents=list(available_agents),
                skipped_agents=[],
                gate_duration_ms=duration_ms,
                reasoning=(
                    "Malformed framing output — defaulting to high "
                    "complexity, dispatching all agents"
                ),
            )

        # Classify intent and complexity
        intent = classify_intent(framing_output)
        complexity = classify_complexity(framing_output)

        # Cap complexity for simple intents: overview questions should never
        # trigger a full agent dispatch just because the LLM over-generated
        # hypotheses. Cap at MEDIUM so the relevance map controls dispatch.
        if intent == IntentCategory.OVERVIEW and complexity == ComplexityLevel.HIGH:
            logger.info(
                "Capping complexity from HIGH to MEDIUM for overview intent "
                "(LLM likely over-generated hypotheses for a simple question)"
            )
            complexity = ComplexityLevel.MEDIUM

        # Determine dispatched agents
        if complexity == ComplexityLevel.HIGH:
            dispatched = set(available_agents)
        else:
            # Look up relevant agents from the relevance map
            map_key = (intent, complexity)
            relevant_from_map = self.relevance_map.get(
                map_key, set(available_agents)
            )
            # Always include question-framing (already ran in tier 1)
            dispatched = set(relevant_from_map)
            if _ALWAYS_INCLUDED_AGENT in available_agents:
                dispatched.add(_ALWAYS_INCLUDED_AGENT)

        # Resolve DAG dependencies to ensure integrity
        from app.orchestration.dag_resolver import resolve_gated_dependencies

        # Use the full registry nodes for proper dependency resolution
        registry_agents = [
            a for a in self._registry_agents
            if a.name in available_agents
        ]
        dispatched = resolve_gated_dependencies(dispatched, registry_agents)

        # Filter to only agents that are actually available
        dispatched = dispatched & set(available_agents)

        # Enforce agent count cap: ≤5 for deep_dive + low complexity
        if execution_plan == "deep_dive" and complexity == ComplexityLevel.LOW:
            if len(dispatched) > 5:
                dispatched = self._cap_agents(dispatched, available_agents)

        # Build the dispatched and skipped lists
        dispatched_list = sorted(dispatched)
        skipped_agents = self._build_skipped_agents(
            available_agents, dispatched, intent, complexity
        )

        duration_ms = (time.perf_counter_ns() - start_ns) // 1_000_000

        reasoning = (
            f"Question classified as {intent.value}/{complexity.value} "
            f"— dispatching {len(dispatched_list)} of "
            f"{len(available_agents)} available agents"
        )

        return GatingDecision(
            intent=intent,
            complexity=complexity,
            dispatched_agents=dispatched_list,
            skipped_agents=skipped_agents,
            gate_duration_ms=duration_ms,
            reasoning=reasoning,
        )

    def _build_skipped_agents(
        self,
        available_agents: list[str],
        dispatched: set[str],
        intent: IntentCategory,
        complexity: ComplexityLevel,
    ) -> list[SkippedAgent]:
        """Build the list of agents that were excluded from dispatch."""
        tier_map = {a.name: a.tier for a in self._registry_agents}
        skipped: list[SkippedAgent] = []
        for agent_name in available_agents:
            if agent_name in dispatched:
                continue
            reason = self._build_skip_reason(agent_name, intent, complexity)
            agent_tier = tier_map.get(agent_name)
            if agent_tier is not None and agent_tier < 0:
                agent_tier = None
            skipped.append(SkippedAgent(name=agent_name, tier=agent_tier, reason=reason))
        return skipped

    def _cap_agents(
        self, dispatched: set[str], available_agents: list[str]
    ) -> set[str]:
        """Cap dispatched agents to 5 for deep_dive + low complexity.

        Priority order for keeping agents:
        1. question-framing (always first)
        2. Mandatory agents (data-explorer, storytelling)
        3. Remaining agents in their available_agents order
        """
        priority_agents = ["question-framing", "data-explorer", "storytelling"]
        kept: set[str] = set()

        # Add priority agents first
        for agent in priority_agents:
            if agent in dispatched and len(kept) < 5:
                kept.add(agent)

        # Fill remaining slots from dispatched in available_agents order
        for agent in available_agents:
            if len(kept) >= 5:
                break
            if agent in dispatched and agent not in kept:
                kept.add(agent)

        return kept

    def _build_skip_reason(
        self,
        agent_name: str,
        intent: IntentCategory,
        complexity: ComplexityLevel,
    ) -> str:
        """Generate a human-readable reason for why an agent was skipped."""
        reason_map = {
            "hypothesis": "No hypotheses requiring testing for this intent",
            "root-cause-investigator": (
                "No root-cause investigation needed for this intent"
            ),
            "overtime-trend": "No temporal scope detected in framing output",
            "source-tieout": (
                "Source tie-out not required for this complexity level"
            ),
            "validation": (
                "Validation skipped for low-complexity analysis"
            ),
            "descriptive-analytics": (
                "Descriptive analytics not needed for this intent"
            ),
            "chart-maker": "Chart generation not required for this intent",
        }

        specific_reason = reason_map.get(agent_name)
        if specific_reason:
            return specific_reason

        return (
            f"Not relevant for {intent.value}/{complexity.value} "
            f"classification"
        )
