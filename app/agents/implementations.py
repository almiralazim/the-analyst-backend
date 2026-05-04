"""Concrete agent implementations for the MVP pipeline.

Each agent registers itself via the @register_agent decorator.
For the MVP, most agents use the GenericAgent with their prompt template.
Agents that need specific helper integration override run_helpers().
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from app.agents.base import BaseAgent
from app.agents.runner import register_agent
from app.config import settings
from app.helpers.chart_helper import ChartSpec, generate_charts
from app.helpers.validation_stack import run_validation
from app.orchestration.context import PipelineContext

logger = logging.getLogger(__name__)


@register_agent
class QuestionFramingAgent(BaseAgent):
    name = "question-framing"
    prompt_template = "question-framing.md"
    system_prompt = (
        "You are a question framing specialist. Transform vague business questions "
        "into structured analytical questions with clear success criteria, "
        "required data, and testable hypotheses."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "QUESTION": context.question,
            "AVAILABLE_DATA": _schema_summary(context),
            "BUSINESS_CONTEXT": "\n".join(
                l.get("content", "") for l in context.learnings
                if l.get("category") == "business_context"
            ) or "No business context available.",
        }


@register_agent
class DataExplorerAgent(BaseAgent):
    name = "data-explorer"
    prompt_template = "data-explorer.md"
    system_prompt = (
        "You are a data exploration specialist. Profile datasets to understand "
        "schema, distributions, quality issues, and relationships between tables."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "DATA_SOURCE": context.duckdb_path,
            "SCHEMA": _schema_summary(context),
            "ANALYSIS_GOALS": context.question,
        }


@register_agent
class HypothesisAgent(BaseAgent):
    name = "hypothesis"
    prompt_template = "hypothesis.md"
    system_prompt = (
        "You are a hypothesis generation specialist. Generate testable hypotheses "
        "across four categories: product changes, technical issues, external factors, "
        "and mix shift."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "QUESTION_BRIEF": context.get_agent_output("question-framing") or context.question,
            "DATA_INVENTORY": _schema_summary(context),
        }


@register_agent
class SourceTieoutAgent(BaseAgent):
    name = "source-tieout"
    prompt_template = "source-tieout.md"
    is_critical = True
    system_prompt = (
        "You are a data verification specialist. Verify data loading integrity "
        "by comparing foundational metrics across data paths."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "DATA_SOURCE": context.duckdb_path,
            "SCHEMA": _schema_summary(context),
            "DATASET_NAME": _first_table_name(context),
        }


@register_agent
class DescriptiveAnalyticsAgent(BaseAgent):
    name = "descriptive-analytics"
    prompt_template = "descriptive-analytics.md"
    system_prompt = (
        "You are a descriptive analytics specialist. Perform segmentation, "
        "funnel analysis, driver analysis, and concentration analysis."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "QUESTION_BRIEF": _get_question_brief(context),
            "SCHEMA": _schema_summary(context),
            "HYPOTHESIS_DOC": str(context.get_agent_output("hypothesis") or ""),
            "DATA_INVENTORY": str(context.get_agent_output("data-explorer") or ""),
            "DATASET": _first_table_name(context),
        }


@register_agent
class OvertimeTrendAgent(BaseAgent):
    name = "overtime-trend"
    prompt_template = "overtime-trend.md"
    system_prompt = (
        "You are a time-series analysis specialist. Detect trends, anomalies, "
        "seasonality, and structural breaks in temporal data."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "QUESTION_BRIEF": _get_question_brief(context),
            "SCHEMA": _schema_summary(context),
            "DATASET": _first_table_name(context),
        }


@register_agent
class RootCauseInvestigatorAgent(BaseAgent):
    name = "root-cause-investigator"
    prompt_template = "root-cause-investigator.md"
    system_prompt = (
        "You are a root cause investigation specialist. Drill down iteratively "
        "through dimensions to find what explains observed anomalies."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "QUESTION_BRIEF": _get_question_brief(context),
            "SCHEMA": _schema_summary(context),
            "ANALYSIS_RESULTS": str(context.get_agent_output("descriptive-analytics") or ""),
            "DATASET": _first_table_name(context),
        }


@register_agent
class ValidationAgent(BaseAgent):
    name = "validation"
    prompt_template = "validation.md"
    is_critical = True
    system_prompt = (
        "You are a validation specialist. Run a 4-layer verification stack: "
        "structural, logical, business rules, and Simpson's Paradox checks."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "ANALYSIS_RESULTS": str(context.get_agent_output("root-cause-investigator") or ""),
            "SCHEMA": _schema_summary(context),
            "DATASET": _first_table_name(context),
        }

    async def run_helpers(self, parsed: dict, context: PipelineContext) -> dict:
        """Run programmatic validation stack and merge with LLM output."""
        findings = _collect_findings(context)
        source_data = _build_source_data(context)

        try:
            result = run_validation(findings, source_data)
            programmatic = {
                "structural": asdict(result.structural),
                "logical": asdict(result.logical),
                "business_rules": asdict(result.business_rules),
                "simpsons_paradox": asdict(result.simpsons_paradox),
                "overall_grade": result.overall_grade,
                "overall_score": result.overall_score,
                "warnings": result.warnings,
            }
        except Exception:
            logger.exception("Programmatic validation failed")
            programmatic = {"error": "Programmatic validation failed"}

        parsed["programmatic_validation"] = programmatic
        return parsed


@register_agent
class ChartMakerAgent(BaseAgent):
    name = "chart-maker"
    prompt_template = "chart-maker.md"
    system_prompt = (
        "You are a chart creation specialist following Storytelling with Data (SWD) "
        "methodology. Create charts with action titles, minimal clutter, and clear focus."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "ANALYSIS_RESULTS": str(context.get_agent_output("root-cause-investigator") or ""),
            "VALIDATION": str(context.get_agent_output("validation") or ""),
            "SCHEMA": _schema_summary(context),
            "DATASET": _first_table_name(context),
        }

    async def run_helpers(self, parsed: dict, context: PipelineContext) -> dict:
        """Generate chart images from LLM-provided chart specifications."""
        chart_dicts = parsed.get("charts", [])
        if not chart_dicts or not isinstance(chart_dicts, list):
            logger.info("ChartMakerAgent: no chart specs found in LLM output")
            return parsed

        try:
            specs = [
                ChartSpec(
                    chart_type=c.get("chart_type", "bar"),
                    title=c.get("title", "Untitled"),
                    data=c.get("data", {}),
                    x_label=c.get("x_label", ""),
                    y_label=c.get("y_label", ""),
                )
                for c in chart_dicts
                if isinstance(c, dict)
            ]

            output_dir = (
                settings.storage_path
                / str(context.dataset_id)
                / "charts"
                / str(context.run_id)
            )

            results = generate_charts(specs, output_dir)
            parsed["generated_charts"] = [asdict(r) for r in results]
            logger.info(
                "ChartMakerAgent: generated %d charts in %s",
                len(results),
                output_dir,
            )
        except Exception:
            logger.exception("Chart generation failed in ChartMakerAgent")
            parsed["generated_charts"] = []

        return parsed


@register_agent
class StorytellingAgent(BaseAgent):
    name = "storytelling"
    prompt_template = "storytelling.md"
    system_prompt = (
        "You are a narrative specialist. Convert analytical findings into a "
        "stakeholder-ready narrative with executive summary, findings, and recommendations."
    )

    def build_prompt_context(self, context: PipelineContext) -> dict:
        return {
            "QUESTION_BRIEF": _get_question_brief(context),
            "ANALYSIS_RESULTS": str(context.get_agent_output("root-cause-investigator") or ""),
            "VALIDATION": str(context.get_agent_output("validation") or ""),
            "CHARTS": str(context.get_agent_output("chart-maker") or ""),
        }


# --- Helper functions ---

def _schema_summary(context: PipelineContext) -> str:
    """Build a concise schema summary for prompts."""
    profile = context.schema_profile
    if not profile:
        return "No schema available."
    lines = []
    for table in profile.get("tables", []):
        cols = ", ".join(f"{c['name']} ({c.get('type', '?')})" for c in table.get("columns", []))
        lines.append(f"Table '{table['name']}' ({table.get('row_count', '?')} rows): {cols}")
    return "\n".join(lines)


def _first_table_name(context: PipelineContext) -> str:
    tables = context.schema_profile.get("tables", []) if context.schema_profile else []
    return tables[0]["name"] if tables else "dataset"


def _get_question_brief(context: PipelineContext) -> str:
    qf_output = context.get_agent_output("question-framing")
    if qf_output and isinstance(qf_output, dict):
        return qf_output.get("output", {}).get("raw_text", context.question)
    return context.question


def _extract_findings_from_dict(data: dict) -> list[dict]:
    """Extract findings list from a dict, falling back to the dict itself."""
    for key in ("findings", "results", "analysis"):
        items = data.get(key)
        if isinstance(items, list):
            return items
    return [data]


def _collect_findings(context: PipelineContext) -> list[dict]:
    """Gather findings from prior analytics agents for validation."""
    findings: list[dict] = []
    agent_names = [
        "descriptive-analytics",
        "root-cause-investigator",
        "overtime-trend",
    ]
    for name in agent_names:
        output = context.get_agent_output(name)
        if not output:
            continue
        # Agent outputs are wrapped as {"agent": ..., "output": ...}
        inner = output.get("output", output) if isinstance(output, dict) else output
        if isinstance(inner, list):
            findings.extend(inner)
        elif isinstance(inner, dict):
            findings.extend(_extract_findings_from_dict(inner))
    return findings


def _build_source_data(context: PipelineContext) -> dict:
    """Build source data dict from schema profile for validation checks."""
    source_data: dict[str, Any] = {}
    if context.schema_profile:
        source_data["schema"] = context.schema_profile
    return source_data
