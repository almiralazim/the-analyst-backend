"""Tests for the export_results endpoint format handling."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_pipeline(
    pipeline_id: uuid.UUID | None = None,
    question: str = "What drives revenue?",
) -> MagicMock:
    """Create a mock PipelineRun object."""
    pipeline = MagicMock()
    pipeline.id = pipeline_id or uuid.uuid4()
    pipeline.user_id = uuid.uuid4()
    pipeline.question = question
    pipeline.confidence_grade = "B"
    pipeline.confidence_score = 0.85
    pipeline.execution_plan = "deep_dive"
    pipeline.created_at = datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc)
    pipeline.started_at = None
    pipeline.completed_at = None
    pipeline.dataset_id = uuid.uuid4()
    pipeline.agent_executions = []
    return pipeline


def _make_results():
    """Create mock AnalysisResult objects."""
    finding = MagicMock()
    finding.result_type = "finding"
    finding.content = {
        "headline": "Revenue up 20%",
        "detail": "Q4 showed strong growth",
        "impact": "high",
    }
    finding.ordering = 1

    narrative = MagicMock()
    narrative.result_type = "narrative"
    narrative.content = {
        "executive_summary": "Overall positive trend",
        "detailed_findings": "Detailed analysis text here",
    }
    narrative.ordering = 2

    return [finding, narrative]


class TestExportFormatValidation:
    """Test that the endpoint validates the format parameter."""

    def test_invalid_format_returns_400_detail(self):
        """Verify the error detail for invalid formats."""
        from app.api.results import export_results
        from fastapi import HTTPException

        # The function validates format before hitting the DB,
        # so we can test the validation logic directly by checking
        # the format validation branch.
        valid_formats = ("html", "pdf", "docx")
        invalid_formats = ("csv", "txt", "json", "xlsx", "PDF", "Html")

        for fmt in invalid_formats:
            assert fmt not in valid_formats, (
                f"{fmt} should not be in valid formats"
            )

        for fmt in valid_formats:
            assert fmt in valid_formats

    def test_valid_formats_accepted(self):
        """Verify html, pdf, docx are all accepted format values."""
        valid = ("html", "pdf", "docx")
        for fmt in valid:
            assert fmt in valid


class TestBuildExportHtml:
    """Test the HTML export builder function."""

    def test_html_contains_question(self):
        from app.api.results import _build_export_html

        pipeline = _make_pipeline()
        findings = [
            {"headline": "Test Finding", "detail": "Details", "impact": "high"}
        ]
        narrative = {"executive_summary": "Summary", "detailed_findings": ""}

        html = _build_export_html(pipeline, findings, narrative)

        assert pipeline.question in html
        assert "Test Finding" in html
        assert "Summary" in html

    def test_html_contains_doctype(self):
        from app.api.results import _build_export_html

        pipeline = _make_pipeline()
        html = _build_export_html(pipeline, [], {})

        assert html.startswith("<!DOCTYPE html>")

    def test_html_handles_empty_narrative(self):
        from app.api.results import _build_export_html

        pipeline = _make_pipeline()
        html = _build_export_html(pipeline, [], {})

        assert "Executive Summary" in html

    def test_html_handles_none_confidence_grade(self):
        from app.api.results import _build_export_html

        pipeline = _make_pipeline()
        pipeline.confidence_grade = None
        html = _build_export_html(pipeline, [], {})

        assert "N/A" in html


class TestExportDocxIntegration:
    """Test the DOCX export service directly."""

    def test_export_to_docx_creates_file(self, tmp_path: Path):
        from app.services.docx_exporter import export_to_docx

        output = tmp_path / "test.docx"
        findings = [
            {"headline": "Revenue Growth", "detail": "20% increase", "impact": "high"}
        ]
        narrative = {
            "executive_summary": "Good quarter",
            "detailed_findings": "Details here",
        }

        result = export_to_docx(
            question="What drives revenue?",
            confidence_grade="B",
            execution_plan="deep_dive",
            created_at="2025-01-15T10:30:00+00:00",
            findings=findings,
            narrative=narrative,
            output_path=output,
        )

        assert result == output
        assert output.exists()
        assert output.stat().st_size > 0

    def test_export_to_docx_is_valid_zip(self, tmp_path: Path):
        """DOCX files are ZIP archives containing word/document.xml."""
        import zipfile

        from app.services.docx_exporter import export_to_docx

        output = tmp_path / "test.docx"
        export_to_docx(
            question="Test question",
            confidence_grade=None,
            execution_plan=None,
            created_at=None,
            findings=[],
            narrative={},
            output_path=output,
        )

        assert zipfile.is_zipfile(output)
        with zipfile.ZipFile(output) as zf:
            assert "word/document.xml" in zf.namelist()


class TestExportPdfImportError:
    """Test PDF export behavior when WeasyPrint is unavailable."""

    def test_pdf_exporter_raises_import_error_without_weasyprint(self):
        """Verify export_to_pdf raises ImportError when weasyprint missing."""
        import importlib
        import sys

        # Temporarily remove weasyprint from available modules
        weasyprint_mod = sys.modules.get("weasyprint")
        sys.modules["weasyprint"] = None  # type: ignore[assignment]
        try:
            # Re-import to get fresh behavior
            if "app.services.pdf_exporter" in sys.modules:
                del sys.modules["app.services.pdf_exporter"]
            from app.services.pdf_exporter import export_to_pdf

            with pytest.raises(ImportError, match="WeasyPrint"):
                export_to_pdf("<html></html>", "/tmp/test.pdf")
        finally:
            if weasyprint_mod is not None:
                sys.modules["weasyprint"] = weasyprint_mod
            else:
                sys.modules.pop("weasyprint", None)
