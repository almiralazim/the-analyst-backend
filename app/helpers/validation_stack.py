"""Validation stack: 4-layer programmatic verification of analysis findings.

Layers:
  1. Structural — required fields, valid types, internal consistency
  2. Logical — numeric calculations, percentage totals, directional claims
  3. Business rules — domain constraints (non-negative revenue, valid dates, etc.)
  4. Simpson's Paradox — aggregate vs. segment trend reversals
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


REQUIRED_FINDING_FIELDS = ("headline", "detail", "impact", "confidence")
VALID_IMPACT_VALUES = ("high", "medium", "low", "critical", "negligible")
NUMERIC_TOLERANCE = 0.05  # 5% relative tolerance for numeric comparisons
_NO_FINDINGS_MSG = "No findings to validate"

# Weights for computing the overall validation score
LAYER_WEIGHTS = {
    "structural": 0.20,
    "logical": 0.30,
    "business_rules": 0.30,
    "simpsons_paradox": 0.20,
}


@dataclass
class ValidationLayerResult:
    """Result from a single validation layer."""

    status: Literal["pass", "warn", "fail"]
    checks: int
    failures: int
    warnings: int
    details: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Aggregated result from all four validation layers."""

    structural: ValidationLayerResult
    logical: ValidationLayerResult
    business_rules: ValidationLayerResult
    simpsons_paradox: ValidationLayerResult
    overall_grade: str
    overall_score: float
    warnings: list[dict] = field(default_factory=list)


def _determine_status(failures: int, warnings: int) -> Literal["pass", "warn", "fail"]:
    """Map failure/warning counts to a layer status."""
    if failures > 0:
        return "fail"
    if warnings > 0:
        return "warn"
    return "pass"


def _check_nonempty_string(finding: dict, key: str, label: str) -> tuple[int, int, list[str]]:
    """Validate that *key* is a non-empty string. Returns (failures, checks_added, details)."""
    if key not in finding:
        return 0, 0, []
    val = finding[key]
    if not isinstance(val, str) or not val.strip():
        return 1, 1, [f"{label}: '{key}' must be a non-empty string"]
    return 0, 1, []


def _check_impact(finding: dict, label: str) -> tuple[int, int, int, list[str]]:
    """Validate the impact field. Returns (failures, warnings, checks_added, details)."""
    if "impact" not in finding:
        return 0, 0, 0, []
    val = finding["impact"]
    if not isinstance(val, str):
        return 1, 0, 1, [f"{label}: 'impact' must be a string"]
    if val.lower() not in VALID_IMPACT_VALUES:
        return 0, 1, 1, [f"{label}: 'impact' value '{val}' is not a recognized level"]
    return 0, 0, 1, []


def _check_confidence(finding: dict, label: str) -> tuple[int, int, list[str]]:
    """Validate the confidence field. Returns (failures, checks_added, details)."""
    if "confidence" not in finding:
        return 0, 0, []
    conf = finding["confidence"]
    if not isinstance(conf, (int, float)):
        return 1, 1, [f"{label}: 'confidence' must be numeric"]
    if not (0 <= conf <= 1):
        return 1, 1, [f"{label}: 'confidence' {conf} is outside [0, 1]"]
    return 0, 1, []


def validate_structural(findings: list[dict]) -> ValidationLayerResult:
    """Check each finding for required fields, valid types, and internal consistency."""
    checks = 0
    failures = 0
    warnings = 0
    details: list[str] = []

    if not findings:
        return ValidationLayerResult(
            status="pass", checks=1, failures=0, warnings=0,
            details=[_NO_FINDINGS_MSG],
        )

    for idx, finding in enumerate(findings):
        label = f"Finding {idx}"

        for field_name in REQUIRED_FINDING_FIELDS:
            checks += 1
            if field_name not in finding:
                failures += 1
                details.append(f"{label}: missing required field '{field_name}'")

        for key in ("headline", "detail"):
            f, c, d = _check_nonempty_string(finding, key, label)
            failures += f; checks += c; details.extend(d)

        f, w, c, d = _check_impact(finding, label)
        failures += f; warnings += w; checks += c; details.extend(d)

        f, c, d = _check_confidence(finding, label)
        failures += f; checks += c; details.extend(d)

    return ValidationLayerResult(
        status=_determine_status(failures, warnings),
        checks=checks,
        failures=failures,
        warnings=warnings,
        details=details,
    )


def _extract_numeric_claims(finding: dict) -> list[dict[str, Any]]:
    """Extract numeric claims (percentages, totals, deltas) from a finding's detail text."""
    claims: list[dict[str, Any]] = []
    detail = finding.get("detail", "")
    if not isinstance(detail, str):
        return claims

    # Match percentage patterns like "45.2%", "increased by 12%", "decreased 30%"
    pct_pattern = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
    for match in pct_pattern.finditer(detail):
        claims.append({"type": "percentage", "value": float(match.group(1)), "raw": match.group(0)})

    # Match dollar/currency amounts like "$1,234.56" or "revenue of 5000"
    dollar_pattern = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
    for match in dollar_pattern.finditer(detail):
        value_str = match.group(1).replace(",", "")
        claims.append({"type": "currency", "value": float(value_str), "raw": match.group(0)})

    return claims


def _values_match(claimed: float, computed: float, tolerance: float = NUMERIC_TOLERANCE) -> bool:
    """Check if two numeric values match within a relative tolerance."""
    if computed == 0:
        return abs(claimed) < tolerance
    return abs(claimed - computed) / abs(computed) <= tolerance


def _check_plausible_percentages(
    claims: list[dict[str, Any]], label: str,
) -> tuple[int, int, int, list[str]]:
    """Check that percentage claims are within a plausible range. Returns (checks, failures, warnings, details)."""
    checks = 0
    warnings = 0
    details: list[str] = []
    for claim in claims:
        checks += 1
        if claim["type"] == "percentage" and abs(claim["value"]) > 1000:
            warnings += 1
            details.append(
                f"{label}: percentage claim {claim['raw']} exceeds 1000%, may be erroneous"
            )
    return checks, 0, warnings, details


def _cross_check_supporting(
    supporting: dict, computed_values: dict[str, float], label: str,
) -> tuple[int, int, list[str]]:
    """Cross-check supporting_data metrics against computed values. Returns (checks, failures, details)."""
    checks = 0
    failures = 0
    details: list[str] = []
    for metric_name, claimed_value in supporting.items():
        if not isinstance(claimed_value, (int, float)):
            continue
        checks += 1
        if metric_name not in computed_values:
            continue
        computed = computed_values[metric_name]
        if not _values_match(claimed_value, computed):
            failures += 1
            details.append(
                f"{label}: claimed {metric_name}={claimed_value} "
                f"but computed value is {computed}"
            )
    return checks, failures, details


_INCREASE_WORDS = ("increased", "grew", "rose", "higher", "up")
_DECREASE_WORDS = ("decreased", "declined", "fell", "lower", "down", "dropped")


def _check_directional_claims(
    finding: dict, supporting: dict, label: str,
) -> tuple[int, int, list[str]]:
    """Check that directional language matches the sign of the delta. Returns (checks, failures, details)."""
    detail_text = finding.get("detail", "")
    if not isinstance(detail_text, str) or not isinstance(supporting, dict):
        return 0, 0, []
    delta = supporting.get("delta") or supporting.get("change")
    if not isinstance(delta, (int, float)):
        return 0, 0, []
    text_lower = detail_text.lower()
    claims_increase = any(w in text_lower for w in _INCREASE_WORDS)
    claims_decrease = any(w in text_lower for w in _DECREASE_WORDS)
    if claims_increase and delta < 0:
        return 1, 1, [f"{label}: claims increase but delta is {delta}"]
    if claims_decrease and delta > 0:
        return 1, 1, [f"{label}: claims decrease but delta is {delta}"]
    return 1, 0, []


def validate_logical(findings: list[dict], source_data: dict) -> ValidationLayerResult:
    """Verify numeric calculations, percentage totals, and directional claims."""
    checks = 0
    failures = 0
    warnings = 0
    details: list[str] = []

    if not findings:
        return ValidationLayerResult(
            status="pass", checks=1, failures=0, warnings=0,
            details=[_NO_FINDINGS_MSG],
        )

    computed_values: dict[str, float] = source_data.get("computed_values", {})

    for idx, finding in enumerate(findings):
        label = f"Finding {idx}"

        c, f, w, d = _check_plausible_percentages(_extract_numeric_claims(finding), label)
        checks += c; failures += f; warnings += w; details.extend(d)

        supporting = finding.get("supporting_data", {})
        if isinstance(supporting, dict):
            c, f, d = _cross_check_supporting(supporting, computed_values, label)
            checks += c; failures += f; details.extend(d)

        c, f, d = _check_directional_claims(finding, supporting, label)
        checks += c; failures += f; details.extend(d)

    if checks == 0:
        checks = 1

    return ValidationLayerResult(
        status=_determine_status(failures, warnings),
        checks=checks,
        failures=failures,
        warnings=warnings,
        details=details,
    )


def _parse_date(value: str) -> datetime | None:
    """Try to parse a date string in common formats."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


_REVENUE_KEYS = ("revenue", "total_revenue", "net_revenue", "gross_revenue")


def _check_negative_revenue(
    supporting: dict, label: str,
) -> tuple[int, int, list[str]]:
    """Flag negative revenue values. Returns (checks, failures, details)."""
    checks = 0
    failures = 0
    details: list[str] = []
    for key in _REVENUE_KEYS:
        if key not in supporting:
            continue
        checks += 1
        val = supporting[key]
        if isinstance(val, (int, float)) and val < 0:
            failures += 1
            details.append(f"{label}: negative revenue '{key}'={val}")
    return checks, failures, details


def _is_percentage_key(key_lower: str) -> bool:
    return "percent" in key_lower or "pct" in key_lower or key_lower.endswith("_rate")


def _is_change_key(key_lower: str) -> bool:
    return "change" in key_lower or "delta" in key_lower or "growth" in key_lower


def _check_supporting_percentages(
    supporting: dict, label: str,
) -> tuple[int, int, int, list[str]]:
    """Check percentage and change values in supporting data. Returns (checks, failures, warnings, details)."""
    checks = 0
    warnings = 0
    details: list[str] = []
    for key, val in supporting.items():
        if not isinstance(val, (int, float)):
            continue
        key_lower = key.lower()
        if _is_percentage_key(key_lower):
            checks += 1
            if val < 0 or val > 100:
                warnings += 1
                details.append(f"{label}: percentage '{key}'={val} is outside [0, 100]")
        if _is_change_key(key_lower):
            checks += 1
            if abs(val) > 1000:
                warnings += 1
                details.append(f"{label}: percentage change '{key}'={val}% exceeds 1000%")
    return checks, 0, warnings, details


def _check_date_values(
    supporting: dict, label: str,
) -> tuple[int, int, int, list[str]]:
    """Validate date strings in supporting data. Returns (checks, failures, warnings, details)."""
    checks = 0
    failures = 0
    warnings = 0
    details: list[str] = []
    for key, val in supporting.items():
        if not isinstance(val, str):
            continue
        key_lower = key.lower()
        if "date" not in key_lower and "time" not in key_lower:
            continue
        checks += 1
        parsed = _parse_date(val)
        if parsed is None:
            warnings += 1
            details.append(f"{label}: could not parse date '{key}'='{val}'")
        elif parsed.year < 1900 or parsed.year > 2100:
            failures += 1
            details.append(f"{label}: date '{key}'='{val}' is outside reasonable range [1900-2100]")
    return checks, failures, warnings, details


def _check_claims_business(
    finding: dict, label: str,
) -> tuple[int, int, int, list[str]]:
    """Check numeric claims from detail text against business rules. Returns (checks, failures, warnings, details)."""
    checks = 0
    failures = 0
    warnings = 0
    details: list[str] = []
    for claim in _extract_numeric_claims(finding):
        checks += 1
        if claim["type"] == "percentage" and abs(claim["value"]) > 1000:
            warnings += 1
            details.append(f"{label}: percentage claim {claim['raw']} exceeds 1000%")
        elif claim["type"] == "currency" and claim["value"] < 0:
            failures += 1
            details.append(f"{label}: negative currency value {claim['raw']}")
    return checks, failures, warnings, details


def validate_business_rules(findings: list[dict]) -> ValidationLayerResult:
    """Check domain constraints: non-negative revenue, valid dates, reasonable percentages."""
    checks = 0
    failures = 0
    warnings = 0
    details: list[str] = []

    if not findings:
        return ValidationLayerResult(
            status="pass", checks=1, failures=0, warnings=0,
            details=[_NO_FINDINGS_MSG],
        )

    for idx, finding in enumerate(findings):
        label = f"Finding {idx}"
        supporting = finding.get("supporting_data", {})
        if not isinstance(supporting, dict):
            supporting = {}

        c, f, d = _check_negative_revenue(supporting, label)
        checks += c; failures += f; details.extend(d)

        c, f, w, d = _check_supporting_percentages(supporting, label)
        checks += c; failures += f; warnings += w; details.extend(d)

        c, f, w, d = _check_date_values(supporting, label)
        checks += c; failures += f; warnings += w; details.extend(d)

        c, f, w, d = _check_claims_business(finding, label)
        checks += c; failures += f; warnings += w; details.extend(d)

    if checks == 0:
        checks = 1

    return ValidationLayerResult(
        status=_determine_status(failures, warnings),
        checks=checks,
        failures=failures,
        warnings=warnings,
        details=details,
    )


def _get_agg_delta(data: dict) -> float | int | None:
    """Extract a numeric aggregate delta/trend from a dict, or None."""
    if not isinstance(data, dict):
        return None
    val = data.get("delta") or data.get("trend")
    return val if isinstance(val, (int, float)) else None


def _count_reversals(segments: dict, agg_delta: int | float) -> tuple[int, int]:
    """Count how many segments reverse the aggregate trend. Returns (reversals, total)."""
    reversals = 0
    total = 0
    for seg_data in segments.values():
        seg_delta = _get_agg_delta(seg_data)
        if seg_delta is None:
            continue
        total += 1
        if (agg_delta > 0) != (seg_delta > 0):
            reversals += 1
    return reversals, total


def _check_simpsons(
    segments: dict, aggregate: dict, label: str,
) -> tuple[int, int, list[str]]:
    """Check one segments/aggregate pair for Simpson's Paradox. Returns (checks, warnings, details)."""
    if not isinstance(segments, dict) or not segments:
        return 0, 0, []
    agg_delta = _get_agg_delta(aggregate)
    if agg_delta is None:
        return 0, 0, []
    reversals, total = _count_reversals(segments, agg_delta)
    if total > 0 and reversals > total / 2:
        direction = "positive" if agg_delta > 0 else "negative"
        return 1, 1, [
            f"{label}: potential Simpson's Paradox — aggregate trend "
            f"({direction}) reverses in {reversals}/{total} segments"
        ]
    return 1, 0, []


def validate_simpsons_paradox(
    findings: list[dict], source_data: dict,
) -> ValidationLayerResult:
    """Flag findings where aggregate trends reverse at the segment level."""
    checks = 0
    warnings = 0
    details: list[str] = []

    if not findings:
        return ValidationLayerResult(
            status="pass", checks=1, failures=0, warnings=0,
            details=[_NO_FINDINGS_MSG],
        )

    # Check source_data-level Simpson's Paradox
    c, w, d = _check_simpsons(
        source_data.get("segments", {}),
        source_data.get("aggregate", {}),
        "Potential Simpson's Paradox",
    )
    checks += c; warnings += w; details.extend(d)

    # Check per-finding segment data
    for idx, finding in enumerate(findings):
        supporting = finding.get("supporting_data", {})
        if not isinstance(supporting, dict):
            continue
        c, w, d = _check_simpsons(
            supporting.get("segments", {}),
            supporting.get("aggregate", {}),
            f"Finding {idx}",
        )
        checks += c; warnings += w; details.extend(d)

    if checks == 0:
        checks = 1

    return ValidationLayerResult(
        status=_determine_status(0, warnings),
        checks=checks,
        failures=0,
        warnings=warnings,
        details=details,
    )


def _layer_score(result: ValidationLayerResult) -> float:
    """Compute a 0.0-1.0 score for a single validation layer.

    - If there are failures, the score is reduced proportionally to the failure rate.
    - If there are only warnings, the score is reduced less aggressively.
    - A layer with 0 failures and 0 warnings scores 1.0.
    """
    if result.checks == 0:
        return 1.0

    if result.failures > 0:
        # Failures reduce the score based on the failure rate
        failure_rate = result.failures / result.checks
        return max(0.0, 1.0 - failure_rate)

    if result.warnings > 0:
        # Warnings reduce the score less aggressively (half the penalty of failures)
        warning_rate = result.warnings / result.checks
        return max(0.0, 1.0 - (warning_rate * 0.5))

    return 1.0


def _score_to_grade(score: float) -> str:
    """Map a numeric score to a letter grade."""
    if score >= 0.9:
        return "A"
    if score >= 0.8:
        return "B"
    if score >= 0.7:
        return "C"
    if score >= 0.6:
        return "D"
    return "F"


def run_validation(findings: list[dict], source_data: dict) -> ValidationResult:
    """Run all 4 validation layers and compute the overall result.

    Weights: structural 0.20, logical 0.30, business_rules 0.30, simpsons_paradox 0.20.
    """
    structural = validate_structural(findings)
    logical = validate_logical(findings, source_data)
    business_rules = validate_business_rules(findings)
    simpsons_paradox = validate_simpsons_paradox(findings, source_data)

    # Compute weighted overall score
    scores = {
        "structural": _layer_score(structural),
        "logical": _layer_score(logical),
        "business_rules": _layer_score(business_rules),
        "simpsons_paradox": _layer_score(simpsons_paradox),
    }

    overall_score = sum(
        scores[layer] * weight for layer, weight in LAYER_WEIGHTS.items()
    )
    # Clamp to [0.0, 1.0]
    overall_score = max(0.0, min(1.0, overall_score))
    overall_grade = _score_to_grade(overall_score)

    # Collect all warnings across layers
    all_warnings: list[dict] = []
    for layer_name, layer_result in [
        ("structural", structural),
        ("logical", logical),
        ("business_rules", business_rules),
        ("simpsons_paradox", simpsons_paradox),
    ]:
        if layer_result.warnings > 0 or layer_result.failures > 0:
            all_warnings.append({
                "layer": layer_name,
                "status": layer_result.status,
                "failures": layer_result.failures,
                "warnings": layer_result.warnings,
                "details": layer_result.details,
            })

    return ValidationResult(
        structural=structural,
        logical=logical,
        business_rules=business_rules,
        simpsons_paradox=simpsons_paradox,
        overall_grade=overall_grade,
        overall_score=overall_score,
        warnings=all_warnings,
    )
