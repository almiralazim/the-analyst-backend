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
                results.append(AnalysisResult(
                    pipeline_run_id=pipeline_id,
                    result_type="finding",
                    content=finding,
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
