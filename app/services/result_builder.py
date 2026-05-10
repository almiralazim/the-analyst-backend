"""Result builder: extracts findings, charts, narrative from pipeline context and stores them."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.result import AnalysisResult
from app.orchestration.context import PipelineContext


@dataclass
class _OrderCounter:
    value: int = 0

    def next(self) -> int:
        self.value += 1
        return self.value


_VALID_IMPACTS = {"high", "medium", "low"}

# Maps alternate field names from agent outputs to the canonical schema.
_HEADLINE_KEYS = ("headline", "title", "summary", "finding", "name")
_DETAIL_KEYS = ("detail", "narrative", "description", "explanation", "body", "text")
_IMPACT_KEYS = ("impact", "impact_level", "severity", "priority")
_CONFIDENCE_KEYS = ("confidence", "confidence_score", "score")
_SOURCES_KEYS = ("sources", "source", "data_sources", "tables")


def _first_match(data: dict, keys: tuple[str, ...], default=None):
    """Return the value of the first key found in data, or default."""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _normalize_impact(value) -> str:
    """Normalize impact to one of: high, medium, low."""
    if isinstance(value, str):
        lower = value.lower().strip()
        if lower in _VALID_IMPACTS:
            return lower
        # Map common alternate values
        if lower in ("critical", "severe"):
            return "high"
        if lower in ("moderate", "notable"):
            return "medium"
        if lower in ("minor", "negligible", "informational"):
            return "low"
    return "medium"


def _normalize_confidence(value) -> float:
    """Normalize confidence to a float between 0 and 1."""
    if isinstance(value, (int, float)):
        # If > 1, assume it's a percentage
        if value > 1:
            return min(value / 100.0, 1.0)
        return max(0.0, min(float(value), 1.0))
    if isinstance(value, str):
        try:
            parsed = float(value.rstrip("%"))
            if parsed > 1:
                return min(parsed / 100.0, 1.0)
            return max(0.0, min(parsed, 1.0))
        except ValueError:
            pass
    return 0.7


def _normalize_sources(value) -> list[str]:
    """Normalize sources to a list of strings."""
    if isinstance(value, list):
        return [str(s) for s in value if s]
    if isinstance(value, str):
        return [value]
    return []


def _stringify_value(value) -> str:
    """Safely convert a value to a string for text fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        # Try common text-like keys within nested objects
        for key in ("text", "content", "summary", "description", "value"):
            if key in value and isinstance(value[key], str):
                return value[key]
        return str(value)
    return str(value)


def normalize_finding(raw: dict, agent_name: str) -> dict:
    """Normalize a raw finding dict from any agent into the canonical schema.

    Canonical schema:
        {
            "headline": str,
            "detail": str,
            "impact": "high" | "medium" | "low",
            "confidence": float (0-1),
            "sources": list[str],
            "supporting_data": dict,
        }
    """
    headline = _stringify_value(_first_match(raw, _HEADLINE_KEYS))
    detail = _stringify_value(_first_match(raw, _DETAIL_KEYS))
    impact = _normalize_impact(_first_match(raw, _IMPACT_KEYS))
    confidence = _normalize_confidence(_first_match(raw, _CONFIDENCE_KEYS))
    sources = _normalize_sources(_first_match(raw, _SOURCES_KEYS, []))

    if not sources:
        sources = [agent_name]

    # If no headline was found, use a truncated detail or a generic label
    if not headline:
        headline = detail[:120] if detail else f"Finding from {agent_name}"

    # Collect any extra keys as supporting_data
    canonical_keys = set()
    for key_group in (_HEADLINE_KEYS, _DETAIL_KEYS, _IMPACT_KEYS, _CONFIDENCE_KEYS, _SOURCES_KEYS):
        canonical_keys.update(key_group)

    supporting_data = {}
    for key, value in raw.items():
        if key not in canonical_keys and value is not None:
            # Only include serializable scalar/list/dict values
            if isinstance(value, (str, int, float, bool, list, dict)):
                supporting_data[key] = value

    return {
        "headline": headline,
        "detail": detail,
        "impact": impact,
        "confidence": confidence,
        "sources": sources,
        "supporting_data": supporting_data,
    }


def _get_agent_dict(context: PipelineContext, agent_name: str) -> dict | None:
    output = context.get_agent_output(agent_name)
    if output and isinstance(output, dict):
        return output.get("output", {})
    return None


def _extract_findings(
    context: PipelineContext, pipeline_id: uuid.UUID, counter: _OrderCounter,
) -> list[AnalysisResult]:
    results: list[AnalysisResult] = []
    for agent_name in ("descriptive-analytics", "root-cause-investigator", "overtime-trend"):
        agent_output = _get_agent_dict(context, agent_name)
        if not agent_output:
            continue

        findings = agent_output.get("findings", [])
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                normalized = normalize_finding(finding, agent_name)
                results.append(AnalysisResult(
                    pipeline_run_id=pipeline_id,
                    result_type="finding",
                    content=normalized,
                    ordering=counter.next(),
                ))

        if not findings and agent_output.get("raw_text"):
            results.append(AnalysisResult(
                pipeline_run_id=pipeline_id,
                result_type="finding",
                content={
                    "headline": f"Analysis from {agent_name}",
                    "detail": agent_output["raw_text"][:5000],
                    "impact": "medium",
                    "confidence": 0.7,
                    "sources": [agent_name],
                    "supporting_data": {},
                },
                ordering=counter.next(),
            ))
    return results


def _extract_charts(
    context: PipelineContext, pipeline_id: uuid.UUID, counter: _OrderCounter,
) -> list[AnalysisResult]:
    agent_output = _get_agent_dict(context, "chart-maker")
    if not agent_output:
        return []

    charts = agent_output.get("charts", [])
    if not isinstance(charts, list):
        return []

    return [
        AnalysisResult(
            pipeline_run_id=pipeline_id,
            result_type="chart",
            content=chart,
            chart_path=chart.get("path"),
            ordering=counter.next(),
        )
        for chart in charts
    ]


def _extract_narrative(
    context: PipelineContext, pipeline_id: uuid.UUID, counter: _OrderCounter,
) -> list[AnalysisResult]:
    agent_output = _get_agent_dict(context, "storytelling")
    if not agent_output:
        return []

    results = [AnalysisResult(
        pipeline_run_id=pipeline_id,
        result_type="narrative",
        content=agent_output,
        ordering=counter.next(),
    )]

    summary = agent_output.get("executive_summary")
    if summary:
        results.append(AnalysisResult(
            pipeline_run_id=pipeline_id,
            result_type="executive_summary",
            content={"executive_summary": summary},
            ordering=counter.next(),
        ))
    return results


def _extract_validation(
    context: PipelineContext, pipeline_id: uuid.UUID, counter: _OrderCounter,
) -> list[AnalysisResult]:
    agent_output = _get_agent_dict(context, "validation")
    if not agent_output:
        return []

    context.validation_result = agent_output
    return [AnalysisResult(
        pipeline_run_id=pipeline_id,
        result_type="validation",
        content=agent_output,
        ordering=counter.next(),
    )]


async def build_and_store_results(
    db: AsyncSession,
    pipeline_id: uuid.UUID,
    context: PipelineContext,
) -> None:
    """Extract structured results from agent outputs and store in the database."""
    counter = _OrderCounter()

    for result in (
        *_extract_findings(context, pipeline_id, counter),
        *_extract_charts(context, pipeline_id, counter),
        *_extract_narrative(context, pipeline_id, counter),
        *_extract_validation(context, pipeline_id, counter),
    ):
        db.add(result)

    await db.flush()
