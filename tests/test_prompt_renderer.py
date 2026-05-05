"""Tests for the prompt template renderer."""

from __future__ import annotations

from app.llm.prompt_renderer import render_template_string


class TestRenderTemplateString:
    def test_substitutes_simple_variable(self):
        template = "Hello {{QUESTION}}, welcome."
        result = render_template_string(template, {"QUESTION": "Why did revenue drop?"})
        assert result == "Hello Why did revenue drop?, welcome."

    def test_leaves_unresolved_variables(self):
        template = "Data: {{SCHEMA}} and {{MISSING_VAR}}"
        result = render_template_string(template, {"SCHEMA": "sales table"})
        assert "sales table" in result
        assert "{{MISSING_VAR}}" in result

    def test_handles_list_values(self):
        template = "Corrections:\n{{CORRECTIONS}}"
        result = render_template_string(template, {"CORRECTIONS": ["fix 1", "fix 2"]})
        assert "fix 1" in result
        assert "fix 2" in result

    def test_handles_empty_context(self):
        template = "Question: {{QUESTION}}"
        result = render_template_string(template, {})
        assert result == "Question: {{QUESTION}}"

    def test_handles_whitespace_in_variable(self):
        template = "{{ QUESTION }}"
        result = render_template_string(template, {"QUESTION": "test"})
        assert result == "test"

    def test_ignores_non_variable_braces(self):
        template = "JSON: {\"key\": \"value\"}"
        result = render_template_string(template, {})
        assert result == template
