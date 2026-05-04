"""Confidence scoring: compute a 0.0-1.0 score and letter grade from
validation stack results.

The scorer weights four validation layers and maps the weighted sum to
a letter grade (A-F).  Critical failures zero out a layer; warnings
reduce the layer score proportionally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Layer weights must sum to 1.0
LAYER_WEIGHTS: dict[str, float] = {
    "structural": 0.20,
    "logical": 0.30,
    "business_rules": 0.30,
    "simpsons_paradox": 0.20,
}

LAYER_NAMES: tuple[str, ...] = tuple(LAYER_WEIGHTS.keys())


@dataclass
class ConfidenceResult:
    """Outcome of confidence scoring."""

    score: float  # 0.0 - 1.0
    grade: str  # A, B, C, D, F
    breakdown: dict[str, float] = field(default_factory=dict)


def _score_layer(layer: dict[str, Any]) -> float:
    """Compute a 0.0-1.0 score for a single validation layer.

    Rules:
    - status "pass"  → 1.0
    - status "fail"  → 0.0
    - status "warn"  → 1.0 - (warnings / max(checks, 1)) * 0.5
      The reduction is capped so the score never drops below 0.5
      from warnings alone.
    """
    status = layer.get("status", "pass")

    if status == "fail":
        return 0.0
    if status == "pass":
        return 1.0

    # "warn" — proportional reduction
    warnings = layer.get("warnings", 0)
    checks = max(layer.get("checks", 1), 1)
    reduction = (warnings / checks) * 0.5
    return max(0.0, 1.0 - reduction)


def _score_to_grade(score: float) -> str:
    """Map a numeric score to a letter grade.

    A: [0.9, 1.0]
    B: [0.8, 0.9)
    C: [0.7, 0.8)
    D: [0.6, 0.7)
    F: [0.0, 0.6)
    """
    if score >= 0.9:
        return "A"
    if score >= 0.8:
        return "B"
    if score >= 0.7:
        return "C"
    if score >= 0.6:
        return "D"
    return "F"


def compute_confidence(
    validation_result: dict[str, Any],
) -> ConfidenceResult:
    """Compute a confidence score from validation stack results.

    *validation_result* should contain keys for each validation layer
    (``structural``, ``logical``, ``business_rules``,
    ``simpsons_paradox``), each mapping to a dict with at least
    ``status``, ``checks``, ``failures``, and ``warnings``.

    Returns a ``ConfidenceResult`` with the weighted score, letter
    grade, and per-layer breakdown.
    """
    breakdown: dict[str, float] = {}

    for layer_name in LAYER_NAMES:
        layer_data = validation_result.get(layer_name, {})
        if not isinstance(layer_data, dict):
            layer_data = {}
        breakdown[layer_name] = _score_layer(layer_data)

    overall = sum(
        breakdown[name] * LAYER_WEIGHTS[name]
        for name in LAYER_NAMES
    )
    # Clamp to [0.0, 1.0]
    overall = max(0.0, min(1.0, overall))

    return ConfidenceResult(
        score=overall,
        grade=_score_to_grade(overall),
        breakdown=breakdown,
    )
