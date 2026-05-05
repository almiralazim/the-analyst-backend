"""Tests for ValidationAgent.run_helpers() integration with validation stack."""

from __future__ import annotations

import pytest

from app.orchestration.context import PipelineContext


@pytest.fixture
def context_with_findings() -> PipelineContext:
    """Context with prior agent outputs containing findings."""
    ctx = PipelineContext(question="Why did revenue drop?")
    ctx.agent_outputs["descriptive-analytics"] = {
        "agent": "descriptive-analytics",
        "output": {
            "findings": [
                {
                    "headline": "Revenue dropped 15%",
                    "detail": "Revenue decreased by 15% in Q3",
                    "impact": "high",
                    "confidence": 0.85,
                    "supporting_data": {"delta": -15},
                },
            ],
        },
    }
    ctx.agent_outputs["root-cause-investigator"] = {
        "agent": "root-cause-investigator",
        "output": {
            "findings": [
                {
                    "headline": "Churn in enterprise segment",
                    "detail": "Enterprise churn increased by 8%",
                    "impact": "high",
                    "confidence": 0.9,
                    "supporting_data": {"delta": 8},
                },
            ],
        },
    }
    return ctx


@pytest.fixture
def empty_context() -> PipelineContext:
    """Context with no prior agent outputs."""
    return PipelineContext(question="Test question")


@pytest.mark.asyncio
async def test_run_helpers_merges_programmatic_validation(
    context_with_findings,
):
    """run_helpers adds programmatic_validation to the parsed output."""
    from app.agents.implementations import ValidationAgent

    agent = ValidationAgent.__new__(ValidationAgent)
    parsed = {"raw_text": "LLM validation output"}

    result = await agent.run_helpers(parsed, context_with_findings)

    assert "programmatic_validation" in result
    pv = result["programmatic_validation"]
    assert "structural" in pv
    assert "logical" in pv
    assert "business_rules" in pv
    assert "simpsons_paradox" in pv
    assert "overall_grade" in pv
    assert "overall_score" in pv
    assert isinstance(pv["overall_score"], float)
    assert 0.0 <= pv["overall_score"] <= 1.0


@pytest.mark.asyncio
async def test_run_helpers_preserves_llm_output(context_with_findings):
    """run_helpers preserves the original LLM-parsed output."""
    from app.agents.implementations import ValidationAgent

    agent = ValidationAgent.__new__(ValidationAgent)
    parsed = {"raw_text": "LLM says all good", "parsed": False}

    result = await agent.run_helpers(parsed, context_with_findings)

    assert result["raw_text"] == "LLM says all good"
    assert result["parsed"] is False
    assert "programmatic_validation" in result


@pytest.mark.asyncio
async def test_run_helpers_with_empty_context(empty_context):
    """run_helpers works when no prior agent outputs exist."""
    from app.agents.implementations import ValidationAgent

    agent = ValidationAgent.__new__(ValidationAgent)
    parsed = {"validation": "LLM output"}

    result = await agent.run_helpers(parsed, empty_context)

    assert "programmatic_validation" in result
    pv = result["programmatic_validation"]
    # With no findings, all layers should pass
    assert pv["structural"]["status"] == "pass"
    assert pv["logical"]["status"] == "pass"
    assert pv["overall_grade"] == "A"


@pytest.mark.asyncio
async def test_run_helpers_with_invalid_findings(empty_context):
    """run_helpers handles findings with missing required fields."""
    from app.agents.implementations import ValidationAgent

    agent = ValidationAgent.__new__(ValidationAgent)
    # Add a finding missing required fields
    empty_context.agent_outputs["descriptive-analytics"] = {
        "agent": "descriptive-analytics",
        "output": {"findings": [{"headline": "Incomplete finding"}]},
    }
    parsed = {}

    result = await agent.run_helpers(parsed, empty_context)

    pv = result["programmatic_validation"]
    # Structural validation should catch missing fields
    assert pv["structural"]["failures"] > 0
    assert pv["structural"]["status"] == "fail"


@pytest.mark.asyncio
async def test_run_helpers_layer_results_have_expected_shape(
    context_with_findings,
):
    """Each validation layer result has the expected fields."""
    from app.agents.implementations import ValidationAgent

    agent = ValidationAgent.__new__(ValidationAgent)
    parsed = {}

    result = await agent.run_helpers(parsed, context_with_findings)

    pv = result["programmatic_validation"]
    for layer in ("structural", "logical", "business_rules", "simpsons_paradox"):
        layer_result = pv[layer]
        assert "status" in layer_result
        assert "checks" in layer_result
        assert "failures" in layer_result
        assert "warnings" in layer_result
        assert "details" in layer_result
        assert layer_result["status"] in ("pass", "warn", "fail")


def test_collect_findings_extracts_from_multiple_agents():
    """_collect_findings gathers findings from all analytics agents."""
    from app.agents.implementations import _collect_findings

    ctx = PipelineContext(question="test")
    ctx.agent_outputs["descriptive-analytics"] = {
        "output": [
            {"headline": "Finding A", "detail": "d", "impact": "high", "confidence": 0.9},
        ],
    }
    ctx.agent_outputs["overtime-trend"] = {
        "output": {
            "findings": [
                {"headline": "Finding B", "detail": "d", "impact": "low", "confidence": 0.7},
            ],
        },
    }

    findings = _collect_findings(ctx)

    headlines = [f["headline"] for f in findings]
    assert "Finding A" in headlines
    assert "Finding B" in headlines


def test_collect_findings_returns_empty_when_no_outputs():
    """_collect_findings returns empty list when no agents have run."""
    from app.agents.implementations import _collect_findings

    ctx = PipelineContext(question="test")
    assert _collect_findings(ctx) == []


def test_build_source_data_includes_schema():
    """_build_source_data includes schema profile when available."""
    from app.agents.implementations import _build_source_data

    ctx = PipelineContext(question="test")
    ctx.schema_profile = {"tables": [{"name": "orders", "columns": []}]}

    source = _build_source_data(ctx)

    assert "schema" in source
    assert source["schema"]["tables"][0]["name"] == "orders"


def test_build_source_data_empty_without_schema():
    """_build_source_data returns empty dict when no schema is available."""
    from app.agents.implementations import _build_source_data

    ctx = PipelineContext(question="test")
    ctx.schema_profile = {}

    source = _build_source_data(ctx)

    assert source == {}
