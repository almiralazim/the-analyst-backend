"""Concrete agent implementations for the MVP pipeline.

Each agent registers itself via the @register_agent decorator.
For the MVP, most agents use the GenericAgent with their prompt template.
Agents that need specific helper integration override run_helpers().
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.agents.runner import register_agent
from app.config import settings
from app.helpers.chart_helper import ChartSpec, generate_charts
from app.helpers.sql_helpers import execute_query, QueryResult, QueryError
from app.helpers.analytics_helpers import (
    compute_summary_stats,
    compute_time_series,
    compute_segmentation,
    compute_top_n,
    detect_anomalies,
    SummaryStats,
)
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

    async def run_helpers(self, parsed: dict, context: PipelineContext) -> dict:
        """Compute summary statistics for dataset columns."""
        query_metadata: list[dict[str, Any]] = []

        if not context.duckdb_path or not Path(context.duckdb_path).exists():
            parsed["query_metadata"] = query_metadata
            return parsed

        try:
            table_name = _first_table_name(context)
            tables = (context.schema_profile or {}).get("tables", [])
            columns: list[str] = []
            if tables:
                columns = [
                    c["name"] for c in tables[0].get("columns", [])
                ]

            if not columns:
                parsed["query_metadata"] = query_metadata
                return parsed

            result = compute_summary_stats(
                context.duckdb_path, table_name, columns
            )

            if isinstance(result, QueryError):
                query_metadata.append({
                    "query": result.query,
                    "error": result.message,
                    "status": "failed",
                })
            else:
                profiles = [asdict(s) for s in result]
                parsed["computed_profiles"] = profiles
                # Store a synthetic QueryResult for context tracking
                synthetic = QueryResult(
                    columns=["column", "stats"],
                    rows=[[s.column, "computed"] for s in result],
                    row_count=len(result),
                    execution_time_ms=0.0,
                    query="compute_summary_stats",
                )
                context.store_query_result(self.name, synthetic)
                query_metadata.append({
                    "query": "compute_summary_stats",
                    "execution_time_ms": 0.0,
                    "row_count": len(result),
                    "status": "success",
                })
        except Exception as exc:
            logger.exception(
                "Unexpected error in %s run_helpers", self.name
            )
            query_metadata.append({
                "error": str(exc), "status": "error",
            })

        parsed["query_metadata"] = query_metadata
        return parsed


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

    async def run_helpers(self, parsed: dict, context: PipelineContext) -> dict:
        """Run verification queries: row counts and numeric sums."""
        query_metadata: list[dict[str, Any]] = []

        if not context.duckdb_path or not Path(context.duckdb_path).exists():
            parsed["query_metadata"] = query_metadata
            return parsed

        try:
            table_name = _first_table_name(context)
            tables = (context.schema_profile or {}).get("tables", [])
            columns = tables[0].get("columns", []) if tables else []

            verification_checks: list[dict[str, Any]] = []

            # Row count check
            count_sql = f'SELECT COUNT(*) FROM "{table_name}"'
            count_result = execute_query(context.duckdb_path, count_sql)
            if isinstance(count_result, QueryResult):
                context.store_query_result(self.name, count_result)
                row_count = count_result.rows[0][0] if count_result.rows else 0
                verification_checks.append({
                    "check": "row_count",
                    "table": table_name,
                    "value": row_count,
                })
                query_metadata.append({
                    "query": count_result.query,
                    "execution_time_ms": count_result.execution_time_ms,
                    "row_count": count_result.row_count,
                    "status": "success",
                })
            else:
                query_metadata.append({
                    "query": count_result.query,
                    "error": count_result.message,
                    "status": "failed",
                })

            # Numeric column sums
            numeric_types = (
                "integer", "int", "bigint", "smallint", "tinyint",
                "float", "double", "real", "decimal", "numeric",
            )
            for col in columns:
                col_type = col.get("type", "").lower()
                if any(col_type.startswith(t) for t in numeric_types):
                    col_name = col["name"]
                    sum_sql = (
                        f'SELECT SUM("{col_name}") FROM "{table_name}"'
                    )
                    sum_result = execute_query(
                        context.duckdb_path, sum_sql
                    )
                    if isinstance(sum_result, QueryResult):
                        context.store_query_result(self.name, sum_result)
                        val = sum_result.rows[0][0] if sum_result.rows else None
                        verification_checks.append({
                            "check": "numeric_sum",
                            "column": col_name,
                            "value": val,
                        })
                        query_metadata.append({
                            "query": sum_result.query,
                            "execution_time_ms": sum_result.execution_time_ms,
                            "row_count": sum_result.row_count,
                            "status": "success",
                        })
                    else:
                        query_metadata.append({
                            "query": sum_result.query,
                            "error": sum_result.message,
                            "status": "failed",
                        })

            parsed["verification_checks"] = verification_checks
        except Exception as exc:
            logger.exception(
                "Unexpected error in %s run_helpers", self.name
            )
            query_metadata.append({
                "error": str(exc), "status": "error",
            })

        parsed["query_metadata"] = query_metadata
        return parsed


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

    async def run_helpers(self, parsed: dict, context: PipelineContext) -> dict:
        """Compute segmentation and top-N analysis."""
        query_metadata: list[dict[str, Any]] = []

        if not context.duckdb_path or not Path(context.duckdb_path).exists():
            parsed["query_metadata"] = query_metadata
            return parsed

        try:
            table_name = _first_table_name(context)
            tables = (context.schema_profile or {}).get("tables", [])
            columns = tables[0].get("columns", []) if tables else []

            # Identify categorical and metric columns
            numeric_types = (
                "integer", "int", "bigint", "smallint", "tinyint",
                "float", "double", "real", "decimal", "numeric",
            )
            categorical_cols = [
                c["name"] for c in columns
                if not any(
                    c.get("type", "").lower().startswith(t)
                    for t in numeric_types
                )
            ]
            metric_cols = [
                c["name"] for c in columns
                if any(
                    c.get("type", "").lower().startswith(t)
                    for t in numeric_types
                )
            ]

            computed_segments: list[dict[str, Any]] = []
            computed_top_n: list[dict[str, Any]] = []

            # Segmentation: first categorical × first metric
            if categorical_cols and metric_cols:
                seg_result = compute_segmentation(
                    context.duckdb_path,
                    table_name,
                    categorical_cols[0],
                    metric_cols[0],
                )
                if isinstance(seg_result, QueryError):
                    query_metadata.append({
                        "query": seg_result.query,
                        "error": seg_result.message,
                        "status": "failed",
                    })
                else:
                    computed_segments = [asdict(s) for s in seg_result]
                    synthetic = QueryResult(
                        columns=["segment", "sum_value", "mean_value", "count", "share_pct"],
                        rows=[[s.segment, s.sum_value, s.mean_value, s.count, s.share_pct] for s in seg_result],
                        row_count=len(seg_result),
                        execution_time_ms=0.0,
                        query="compute_segmentation",
                    )
                    context.store_query_result(self.name, synthetic)
                    query_metadata.append({
                        "query": "compute_segmentation",
                        "execution_time_ms": 0.0,
                        "row_count": len(seg_result),
                        "status": "success",
                    })

                # Top-N: first categorical × first metric
                top_result = compute_top_n(
                    context.duckdb_path,
                    table_name,
                    categorical_cols[0],
                    metric_cols[0],
                )
                if isinstance(top_result, QueryError):
                    query_metadata.append({
                        "query": top_result.query,
                        "error": top_result.message,
                        "status": "failed",
                    })
                else:
                    computed_top_n = [asdict(g) for g in top_result]
                    synthetic = QueryResult(
                        columns=["group", "metric_value", "row_count", "share_pct"],
                        rows=[[g.group, g.metric_value, g.row_count, g.share_pct] for g in top_result],
                        row_count=len(top_result),
                        execution_time_ms=0.0,
                        query="compute_top_n",
                    )
                    context.store_query_result(self.name, synthetic)
                    query_metadata.append({
                        "query": "compute_top_n",
                        "execution_time_ms": 0.0,
                        "row_count": len(top_result),
                        "status": "success",
                    })

            parsed["computed_segments"] = computed_segments
            parsed["computed_top_n"] = computed_top_n
        except Exception as exc:
            logger.exception(
                "Unexpected error in %s run_helpers", self.name
            )
            query_metadata.append({
                "error": str(exc), "status": "error",
            })

        parsed["query_metadata"] = query_metadata
        return parsed


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

    async def run_helpers(self, parsed: dict, context: PipelineContext) -> dict:
        """Compute time series and detect anomalies."""
        query_metadata: list[dict[str, Any]] = []

        if not context.duckdb_path or not Path(context.duckdb_path).exists():
            parsed["query_metadata"] = query_metadata
            return parsed

        try:
            table_name = _first_table_name(context)
            tables = (context.schema_profile or {}).get("tables", [])
            columns = tables[0].get("columns", []) if tables else []

            # Identify date and metric columns
            date_types = ("date", "timestamp", "time")
            numeric_types = (
                "integer", "int", "bigint", "smallint", "tinyint",
                "float", "double", "real", "decimal", "numeric",
            )
            date_cols = [
                c["name"] for c in columns
                if any(
                    c.get("type", "").lower().startswith(t)
                    for t in date_types
                )
            ]
            metric_cols = [
                c["name"] for c in columns
                if any(
                    c.get("type", "").lower().startswith(t)
                    for t in numeric_types
                )
            ]

            computed_time_series: list[dict[str, Any]] = []
            computed_anomalies: list[dict[str, Any]] = []

            if date_cols and metric_cols:
                date_col = date_cols[0]
                metric_col = metric_cols[0]

                # Time series (monthly)
                ts_result = compute_time_series(
                    context.duckdb_path,
                    table_name,
                    date_col,
                    metric_col,
                    "month",
                )
                if isinstance(ts_result, QueryError):
                    query_metadata.append({
                        "query": ts_result.query,
                        "error": ts_result.message,
                        "status": "failed",
                    })
                else:
                    computed_time_series = [asdict(p) for p in ts_result]
                    synthetic = QueryResult(
                        columns=["period", "value", "row_count"],
                        rows=[[p.period, p.value, p.row_count] for p in ts_result],
                        row_count=len(ts_result),
                        execution_time_ms=0.0,
                        query="compute_time_series",
                    )
                    context.store_query_result(self.name, synthetic)
                    query_metadata.append({
                        "query": "compute_time_series",
                        "execution_time_ms": 0.0,
                        "row_count": len(ts_result),
                        "status": "success",
                    })

                # Anomaly detection
                anomaly_result = detect_anomalies(
                    context.duckdb_path,
                    table_name,
                    date_col,
                    metric_col,
                )
                if isinstance(anomaly_result, QueryError):
                    query_metadata.append({
                        "query": anomaly_result.query,
                        "error": anomaly_result.message,
                        "status": "failed",
                    })
                else:
                    computed_anomalies = [asdict(a) for a in anomaly_result]
                    synthetic = QueryResult(
                        columns=["date", "actual", "expected", "deviation_sigma", "direction"],
                        rows=[[a.date, a.actual, a.expected, a.deviation_sigma, a.direction] for a in anomaly_result],
                        row_count=len(anomaly_result),
                        execution_time_ms=0.0,
                        query="detect_anomalies",
                    )
                    context.store_query_result(self.name, synthetic)
                    query_metadata.append({
                        "query": "detect_anomalies",
                        "execution_time_ms": 0.0,
                        "row_count": len(anomaly_result),
                        "status": "success",
                    })

            parsed["computed_time_series"] = computed_time_series
            parsed["computed_anomalies"] = computed_anomalies
        except Exception as exc:
            logger.exception(
                "Unexpected error in %s run_helpers", self.name
            )
            query_metadata.append({
                "error": str(exc), "status": "error",
            })

        parsed["query_metadata"] = query_metadata
        return parsed


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

    async def run_helpers(self, parsed: dict, context: PipelineContext) -> dict:
        """Execute drill-down SQL queries from LLM output."""
        query_metadata: list[dict[str, Any]] = []

        if not context.duckdb_path or not Path(context.duckdb_path).exists():
            parsed["query_metadata"] = query_metadata
            return parsed

        try:
            # Extract SQL queries from the LLM's parsed output
            queries = parsed.get("queries", [])
            drill_down_results: list[dict[str, Any]] = []

            for sql in queries:
                if not isinstance(sql, str) or not sql.strip():
                    continue
                result = execute_query(context.duckdb_path, sql)
                if isinstance(result, QueryResult):
                    context.store_query_result(self.name, result)
                    drill_down_results.append({
                        "query": result.query,
                        "columns": result.columns,
                        "rows": result.rows,
                        "row_count": result.row_count,
                    })
                    query_metadata.append({
                        "query": result.query,
                        "execution_time_ms": result.execution_time_ms,
                        "row_count": result.row_count,
                        "status": "success",
                    })
                else:
                    drill_down_results.append({
                        "query": result.query,
                        "error": result.message,
                    })
                    query_metadata.append({
                        "query": result.query,
                        "error": result.message,
                        "status": "failed",
                    })

            parsed["drill_down_results"] = drill_down_results
        except Exception as exc:
            logger.exception(
                "Unexpected error in %s run_helpers", self.name
            )
            query_metadata.append({
                "error": str(exc), "status": "error",
            })

        parsed["query_metadata"] = query_metadata
        return parsed


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
        """Execute data queries and generate chart images."""
        query_metadata: list[dict[str, Any]] = []

        # Execute data queries if present in LLM output
        if (
            context.duckdb_path
            and Path(context.duckdb_path).exists()
            and parsed.get("data_queries")
            and isinstance(parsed["data_queries"], list)
        ):
            try:
                for sql in parsed["data_queries"]:
                    if not isinstance(sql, str) or not sql.strip():
                        continue
                    result = execute_query(context.duckdb_path, sql)
                    if isinstance(result, QueryResult):
                        context.store_query_result(self.name, result)
                        query_metadata.append({
                            "query": result.query,
                            "execution_time_ms": result.execution_time_ms,
                            "row_count": result.row_count,
                            "status": "success",
                        })
                    else:
                        query_metadata.append({
                            "query": result.query,
                            "error": result.message,
                            "status": "failed",
                        })
            except Exception as exc:
                logger.exception(
                    "Data query execution failed in %s", self.name
                )
                query_metadata.append({
                    "error": str(exc), "status": "error",
                })

        # Generate charts from LLM-provided specs
        chart_dicts = parsed.get("charts", [])
        if not chart_dicts or not isinstance(chart_dicts, list):
            logger.info("ChartMakerAgent: no chart specs found in LLM output")
            parsed["query_metadata"] = query_metadata
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

        parsed["query_metadata"] = query_metadata
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
