"""Auto plan selector: downgrades deep_dive to quick_overview for simple questions.

This is a zero-LLM-cost pre-gate classifier that runs before any agents.
It uses keyword/pattern matching on the raw question text to detect simple
exploratory questions that don't need the full 10-agent pipeline.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Questions that match these patterns are simple overviews that don't need
# hypothesis testing, root-cause investigation, or validation.
_OVERVIEW_PATTERNS: list[re.Pattern] = [
    # "tell me about" / "describe" / "summarize" the data/dataset
    re.compile(
        r"\b(tell\s+me\s+about|describe|summarize|overview\s+of|"
        r"what\s+is\s+(this|the)\s+(data|dataset)|"
        r"what\s+does\s+(this|the)\s+(data|dataset)\s+(look\s+like|contain)|"
        r"show\s+me\s+(this|the)\s+(data|dataset)|"
        r"what('s|\s+is)\s+in\s+(this|the)\s+(data|dataset|file)|"
        r"give\s+me\s+(a\s+)?(summary|overview|breakdown))\b",
        re.IGNORECASE,
    ),
    # "what columns" / "what tables" / "how many rows"
    re.compile(
        r"\b(what\s+(columns|tables|fields|variables)|"
        r"how\s+many\s+(rows|records|entries|columns)|"
        r"list\s+(the\s+)?(columns|tables|fields)|"
        r"schema|structure|shape)\b",
        re.IGNORECASE,
    ),
    # "profile" / "explore" the data
    re.compile(
        r"\b(profile|explore|inspect|examine)\s+(this|the|my)?\s*(data|dataset|file)\b",
        re.IGNORECASE,
    ),
]

# Questions that match these patterns are complex and should NEVER be
# downgraded, even if they also match an overview pattern.
_COMPLEX_PATTERNS: list[re.Pattern] = [
    # Root cause / why questions
    re.compile(
        r"\b(why\s+(did|does|is|are|has|have|was|were)|"
        r"what\s+(caused|drove|drives|explains)|"
        r"root\s+cause|driver\s+of)\b",
        re.IGNORECASE,
    ),
    # Trend / time-based analysis
    re.compile(
        r"\b(over\s+time|trend|month\s+over\s+month|year\s+over\s+year|"
        r"yoy|mom|qoq|quarter\s+over\s+quarter|"
        r"compared\s+to\s+(last|previous)|"
        r"changed?\s+(since|from|between)|"
        r"growth|decline|increase|decrease)\b",
        re.IGNORECASE,
    ),
    # Hypothesis / investigation
    re.compile(
        r"\b(hypothesis|hypotheses|investigat\w*|correlat\w*|predict\w*|forecast\w*|"
        r"regression|significance|anomal\w*|outlier\w*)\b",
        re.IGNORECASE,
    ),
    # Comparison between segments
    re.compile(
        r"\b(compare|versus|vs\.?|difference\s+between|"
        r"which\s+(segment|group|region|product|channel)\s+(is|has|performs))\b",
        re.IGNORECASE,
    ),
]


def should_downgrade_to_overview(question: str) -> bool:
    """Determine if a question is simple enough to use quick_overview.

    Returns True if the question matches overview patterns and does NOT
    match any complex patterns. This is intentionally conservative —
    when in doubt, it returns False (keeping deep_dive).

    Args:
        question: The raw user question text.

    Returns:
        True if the question should use quick_overview instead of deep_dive.
    """
    if not question or len(question.strip()) < 5:
        return False

    q = question.strip()

    # Check for complex patterns first (these override overview matches)
    for pattern in _COMPLEX_PATTERNS:
        if pattern.search(q):
            return False

    # Check if it matches an overview pattern
    for pattern in _OVERVIEW_PATTERNS:
        if pattern.search(q):
            return True

    # Short questions (< 40 chars) without specific analytical keywords
    # are likely simple exploratory questions
    if len(q) < 40 and not any(p.search(q) for p in _COMPLEX_PATTERNS):
        # But only if they don't contain question words that imply depth
        deep_question_words = re.compile(
            r"\b(why|how\s+much|what\s+percentage|what\s+fraction|"
            r"which\s+\w+\s+(is|are|has|have)\s+(the\s+)?(most|least|highest|lowest))\b",
            re.IGNORECASE,
        )
        if not deep_question_words.search(q):
            return True

    return False


def auto_select_plan(question: str, requested_plan: str) -> str:
    """Auto-select the execution plan based on question complexity.

    Only downgrades from deep_dive to quick_overview. Never upgrades.
    Respects explicit user choices for other plans.

    Args:
        question: The raw user question text.
        requested_plan: The plan the user/frontend requested.

    Returns:
        The final plan to use (may be downgraded to quick_overview).
    """
    # Only auto-downgrade deep_dive. Other plans are explicit choices.
    if requested_plan != "deep_dive":
        return requested_plan

    if should_downgrade_to_overview(question):
        logger.info(
            "Auto-downgrading plan from deep_dive to quick_overview "
            "for simple question: '%s'",
            question[:80],
        )
        return "quick_overview"

    return requested_plan
