"""Tests for the pipeline context and knowledge formatting."""

from app.orchestration.context import PipelineContext


class TestPipelineContext:
    def test_format_corrections_empty(self):
        ctx = PipelineContext()
        result = ctx.format_corrections_for_prompt()
        assert "No corrections" in result

    def test_format_corrections_with_entries(self):
        ctx = PipelineContext(corrections=[
            {
                "severity": "high",
                "description": "Revenue should exclude refunds",
                "prevention_rule": "Always subtract refunds",
            },
            {
                "severity": "medium",
                "description": "Use order_date not created_at for time analysis",
            },
        ])
        result = ctx.format_corrections_for_prompt()
        assert "HIGH" in result
        assert "Revenue should exclude refunds" in result
        assert "Always subtract refunds" in result
        assert "MEDIUM" in result

    def test_get_agent_output_returns_none_for_missing(self):
        ctx = PipelineContext()
        assert ctx.get_agent_output("nonexistent") is None

    def test_get_agent_output_returns_stored_value(self):
        ctx = PipelineContext()
        ctx.agent_outputs["test-agent"] = {"output": "hello"}
        assert ctx.get_agent_output("test-agent") == {"output": "hello"}
