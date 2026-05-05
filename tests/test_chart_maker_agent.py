"""Tests for ChartMakerAgent.run_helpers() integration with chart helper."""

from __future__ import annotations

import uuid

import pytest

from app.orchestration.context import PipelineContext


@pytest.fixture
def context() -> PipelineContext:
    """Pipeline context with known IDs for predictable output paths."""
    return PipelineContext(
        dataset_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        question="Why did revenue drop?",
    )


@pytest.mark.asyncio
async def test_run_helpers_generates_charts(context, tmp_path, monkeypatch):
    """run_helpers generates charts and adds generated_charts to output."""
    from app.agents.implementations import ChartMakerAgent

    monkeypatch.setattr(
        "app.agents.implementations.settings.storage_dir",
        str(tmp_path),
    )

    agent = ChartMakerAgent.__new__(ChartMakerAgent)
    parsed = {
        "charts": [
            {
                "chart_type": "bar",
                "title": "Revenue by Quarter",
                "data": {
                    "labels": ["Q1", "Q2", "Q3", "Q4"],
                    "datasets": [
                        {"label": "Revenue", "values": [100, 120, 90, 110]},
                    ],
                },
                "x_label": "Quarter",
                "y_label": "Amount ($)",
            },
        ],
    }

    result = await agent.run_helpers(parsed, context)

    assert "generated_charts" in result
    assert len(result["generated_charts"]) == 1
    chart = result["generated_charts"][0]
    assert chart["chart_type"] == "bar"
    assert chart["title"] == "Revenue by Quarter"
    assert "chart_id" in chart
    assert "path" in chart


@pytest.mark.asyncio
async def test_run_helpers_no_charts_key(context):
    """run_helpers returns parsed unchanged when no charts key exists."""
    from app.agents.implementations import ChartMakerAgent

    agent = ChartMakerAgent.__new__(ChartMakerAgent)
    parsed = {"raw_text": "No charts here"}

    result = await agent.run_helpers(parsed, context)

    assert result == parsed
    assert "generated_charts" not in result


@pytest.mark.asyncio
async def test_run_helpers_empty_charts_list(context):
    """run_helpers returns parsed unchanged when charts list is empty."""
    from app.agents.implementations import ChartMakerAgent

    agent = ChartMakerAgent.__new__(ChartMakerAgent)
    parsed = {"charts": []}

    result = await agent.run_helpers(parsed, context)

    assert "generated_charts" not in result


@pytest.mark.asyncio
async def test_run_helpers_preserves_existing_output(
    context, tmp_path, monkeypatch,
):
    """run_helpers preserves the original LLM-parsed output fields."""
    from app.agents.implementations import ChartMakerAgent

    monkeypatch.setattr(
        "app.agents.implementations.settings.storage_dir",
        str(tmp_path),
    )

    agent = ChartMakerAgent.__new__(ChartMakerAgent)
    parsed = {
        "analysis": "Some analysis text",
        "charts": [
            {
                "chart_type": "line",
                "title": "Trend",
                "data": {
                    "labels": ["Jan", "Feb"],
                    "datasets": [{"label": "Users", "values": [10, 20]}],
                },
            },
        ],
    }

    result = await agent.run_helpers(parsed, context)

    assert result["analysis"] == "Some analysis text"
    assert "generated_charts" in result


@pytest.mark.asyncio
async def test_run_helpers_skips_non_dict_chart_specs(
    context, tmp_path, monkeypatch,
):
    """run_helpers filters out non-dict entries in the charts list."""
    from app.agents.implementations import ChartMakerAgent

    monkeypatch.setattr(
        "app.agents.implementations.settings.storage_dir",
        str(tmp_path),
    )

    agent = ChartMakerAgent.__new__(ChartMakerAgent)
    parsed = {
        "charts": [
            "not a dict",
            {
                "chart_type": "bar",
                "title": "Valid Chart",
                "data": {
                    "labels": ["A", "B"],
                    "datasets": [{"label": "X", "values": [1, 2]}],
                },
            },
        ],
    }

    result = await agent.run_helpers(parsed, context)

    assert len(result["generated_charts"]) == 1
    assert result["generated_charts"][0]["title"] == "Valid Chart"


@pytest.mark.asyncio
async def test_run_helpers_output_dir_uses_correct_path(
    context, tmp_path, monkeypatch,
):
    """Charts are saved to storage/{dataset_id}/charts/{run_id}/."""
    from app.agents.implementations import ChartMakerAgent

    monkeypatch.setattr(
        "app.agents.implementations.settings.storage_dir",
        str(tmp_path),
    )

    agent = ChartMakerAgent.__new__(ChartMakerAgent)
    parsed = {
        "charts": [
            {
                "chart_type": "bar",
                "title": "Test",
                "data": {
                    "labels": ["A"],
                    "datasets": [{"label": "S", "values": [1]}],
                },
            },
        ],
    }

    result = await agent.run_helpers(parsed, context)

    expected_dir = (
        tmp_path
        / str(context.dataset_id)
        / "charts"
        / str(context.run_id)
    )
    assert expected_dir.exists()
    chart_path = result["generated_charts"][0]["path"]
    assert str(expected_dir) in chart_path


@pytest.mark.asyncio
async def test_run_helpers_handles_generation_failure_gracefully(
    context, monkeypatch,
):
    """Chart generation failures don't crash the agent."""
    from app.agents.implementations import ChartMakerAgent

    def _boom(*args, **kwargs):
        raise RuntimeError("matplotlib exploded")

    monkeypatch.setattr(
        "app.agents.implementations.generate_charts", _boom,
    )

    agent = ChartMakerAgent.__new__(ChartMakerAgent)
    parsed = {
        "charts": [
            {
                "chart_type": "bar",
                "title": "Will Fail",
                "data": {"labels": ["A"], "datasets": [{"values": [1]}]},
            },
        ],
    }

    result = await agent.run_helpers(parsed, context)

    assert result["generated_charts"] == []
    assert "charts" in result  # original key preserved
