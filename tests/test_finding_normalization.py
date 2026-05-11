"""Tests for finding normalization in the result builder."""

import sys
from unittest.mock import MagicMock
import pytest

# Stub out heavy dependencies so we can import the normalization functions
# without needing a database connection or async drivers.
sys.modules.setdefault("sqlalchemy", MagicMock())
sys.modules.setdefault("sqlalchemy.ext", MagicMock())
sys.modules.setdefault("sqlalchemy.ext.asyncio", MagicMock())
sys.modules.setdefault("app.models.result", MagicMock())
sys.modules.setdefault("app.orchestration.context", MagicMock())

from app.services.result_builder import (  # noqa: E402
    normalize_finding,
    _normalize_confidence,
    _normalize_impact,
    _normalize_sources,
    _stringify_value,
)


class TestNormalizeFinding:
    """Verify that normalize_finding maps various agent output shapes to the canonical schema."""

    def test_canonical_shape_passes_through(self):
        raw = {
            "headline": "Revenue grew 23%",
            "detail": "Enterprise segment drove growth",
            "impact": "high",
            "confidence": 0.95,
            "sources": ["sales.orders"],
        }
        result = normalize_finding(raw, "descriptive-analytics")
        assert result["headline"] == "Revenue grew 23%"
        assert result["detail"] == "Enterprise segment drove growth"
        assert result["impact"] == "high"
        assert result["confidence"] == pytest.approx(0.95)
        assert result["sources"] == ["sales.orders"]

    def test_alternate_shape_with_title_and_narrative(self):
        raw = {
            "title": "Cost anomaly detected",
            "narrative": "Shipping costs spiked 40% in March",
            "impact_level": "high",
            "confidence": 0.88,
            "caveats": ["Limited data for Feb"],
            "supporting_charts": ["chart-1"],
        }
        result = normalize_finding(raw, "root-cause-investigator")
        assert result["headline"] == "Cost anomaly detected"
        assert result["detail"] == "Shipping costs spiked 40% in March"
        assert result["impact"] == "high"
        assert result["confidence"] == pytest.approx(0.88)
        assert result["sources"] == ["root-cause-investigator"]
        assert result["supporting_data"]["caveats"] == ["Limited data for Feb"]
        assert result["supporting_data"]["supporting_charts"] == ["chart-1"]

    def test_missing_headline_uses_detail_truncated(self):
        raw = {
            "detail": "A" * 200,
            "impact": "low",
            "confidence": 0.5,
        }
        result = normalize_finding(raw, "overtime-trend")
        assert result["headline"] == "A" * 120
        assert len(result["headline"]) == 120

    def test_missing_headline_and_detail_uses_agent_name(self):
        raw = {"confidence": 0.6}
        result = normalize_finding(raw, "descriptive-analytics")
        assert result["headline"] == "Finding from descriptive-analytics"
        assert result["detail"] == ""

    def test_impact_normalization_critical(self):
        raw = {"headline": "Test", "impact_level": "critical"}
        result = normalize_finding(raw, "test-agent")
        assert result["impact"] == "high"

    def test_impact_normalization_moderate(self):
        raw = {"headline": "Test", "severity": "moderate"}
        result = normalize_finding(raw, "test-agent")
        assert result["impact"] == "medium"

    def test_impact_normalization_minor(self):
        raw = {"headline": "Test", "impact": "minor"}
        result = normalize_finding(raw, "test-agent")
        assert result["impact"] == "low"

    def test_impact_normalization_unknown_defaults_medium(self):
        raw = {"headline": "Test", "impact": "catastrophic"}
        result = normalize_finding(raw, "test-agent")
        assert result["impact"] == "medium"

    def test_confidence_percentage_normalized(self):
        raw = {"headline": "Test", "confidence": 85}
        result = normalize_finding(raw, "test-agent")
        assert result["confidence"] == pytest.approx(0.85)

    def test_confidence_string_percentage(self):
        raw = {"headline": "Test", "confidence_score": "92%"}
        result = normalize_finding(raw, "test-agent")
        assert result["confidence"] == pytest.approx(0.92)

    def test_confidence_missing_defaults(self):
        raw = {"headline": "Test"}
        result = normalize_finding(raw, "test-agent")
        assert result["confidence"] == pytest.approx(0.7)

    def test_sources_string_becomes_list(self):
        raw = {"headline": "Test", "sources": "sales_data"}
        result = normalize_finding(raw, "test-agent")
        assert result["sources"] == ["sales_data"]

    def test_sources_missing_uses_agent_name(self):
        raw = {"headline": "Test"}
        result = normalize_finding(raw, "test-agent")
        assert result["sources"] == ["test-agent"]

    def test_nested_object_detail_stringified(self):
        raw = {
            "headline": "Test",
            "detail": {"text": "Nested detail content"},
        }
        result = normalize_finding(raw, "test-agent")
        assert result["detail"] == "Nested detail content"

    def test_list_detail_stringified(self):
        raw = {
            "headline": "Test",
            "detail": ["Point 1", "Point 2"],
        }
        result = normalize_finding(raw, "test-agent")
        assert result["detail"] == "Point 1; Point 2"

    def test_all_fields_are_strings_or_primitives(self):
        """Ensure no nested objects leak into text fields that React would choke on."""
        raw = {
            "title": {"nested": "object"},
            "narrative": ["list", "of", "items"],
            "impact_level": "high",
            "confidence": 0.9,
        }
        result = normalize_finding(raw, "test-agent")
        assert isinstance(result["headline"], str)
        assert isinstance(result["detail"], str)
        assert isinstance(result["impact"], str)
        assert isinstance(result["confidence"], float)
        assert isinstance(result["sources"], list)
