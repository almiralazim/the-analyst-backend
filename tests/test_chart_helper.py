"""Tests for app.helpers.chart_helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.helpers.chart_helper import (
    ChartSpec,
    ChartResult,
    convert_chart_format,
    generate_charts,
)

# PNG magic bytes
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _bar_spec(title: str = "Revenue by Quarter") -> ChartSpec:
    return ChartSpec(
        chart_type="bar",
        title=title,
        data={
            "labels": ["Q1", "Q2", "Q3", "Q4"],
            "datasets": [
                {"label": "Revenue", "values": [100, 120, 90, 110]},
                {"label": "Costs", "values": [80, 85, 75, 90]},
            ],
        },
        x_label="Quarter",
        y_label="Amount ($)",
    )


def _line_spec() -> ChartSpec:
    return ChartSpec(
        chart_type="line",
        title="Monthly Trend",
        data={
            "labels": ["Jan", "Feb", "Mar", "Apr"],
            "datasets": [
                {"label": "Users", "values": [10, 20, 15, 25]},
            ],
        },
        x_label="Month",
        y_label="Users",
    )


def _heatmap_spec() -> ChartSpec:
    return ChartSpec(
        chart_type="heatmap",
        title="Activity Heatmap",
        data={
            "x_labels": ["Mon", "Tue", "Wed"],
            "y_labels": ["Morning", "Afternoon"],
            "values": [[10, 20, 30], [15, 25, 35]],
        },
    )


class TestGenerateCharts:
    """Tests for generate_charts()."""

    def test_generates_bar_chart_png(self, tmp_path: Path):
        results = generate_charts([_bar_spec()], tmp_path)
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, ChartResult)
        assert r.chart_type == "bar"
        assert r.title == "Revenue by Quarter"
        png = Path(r.path)
        assert png.exists()
        assert png.read_bytes()[:8] == _PNG_MAGIC

    def test_generates_line_chart_png(self, tmp_path: Path):
        results = generate_charts([_line_spec()], tmp_path)
        assert len(results) == 1
        assert Path(results[0].path).read_bytes()[:8] == _PNG_MAGIC

    def test_generates_heatmap_png(self, tmp_path: Path):
        results = generate_charts([_heatmap_spec()], tmp_path)
        assert len(results) == 1
        assert Path(results[0].path).read_bytes()[:8] == _PNG_MAGIC

    def test_saves_spec_json_alongside_png(self, tmp_path: Path):
        results = generate_charts([_bar_spec()], tmp_path)
        r = results[0]
        spec_path = tmp_path / f"{r.chart_id}.spec.json"
        assert spec_path.exists()
        spec_data = json.loads(spec_path.read_text())
        assert spec_data["chart_type"] == "bar"
        assert spec_data["title"] == "Revenue by Quarter"
        assert spec_data["chart_id"] == r.chart_id

    def test_multiple_charts(self, tmp_path: Path):
        specs = [_bar_spec(), _line_spec(), _heatmap_spec()]
        results = generate_charts(specs, tmp_path)
        assert len(results) == 3
        ids = {r.chart_id for r in results}
        assert len(ids) == 3  # unique IDs

    def test_skips_invalid_spec_without_raising(self, tmp_path: Path):
        """Invalid specs are logged and skipped."""
        bad_spec = ChartSpec(
            chart_type="bar",
            title="Bad Chart",
            data={},  # missing labels/datasets
        )
        good_spec = _line_spec()
        results = generate_charts([bad_spec, good_spec], tmp_path)
        assert len(results) == 1
        assert results[0].chart_type == "line"

    def test_unsupported_chart_type_skipped(self, tmp_path: Path):
        bad_spec = ChartSpec(
            chart_type="pie",  # type: ignore[arg-type]
            title="Pie Chart",
            data={"labels": ["A"], "datasets": [{"values": [1]}]},
        )
        results = generate_charts([bad_spec, _bar_spec()], tmp_path)
        assert len(results) == 1
        assert results[0].chart_type == "bar"

    def test_creates_output_dir_if_missing(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c"
        results = generate_charts([_bar_spec()], nested)
        assert len(results) == 1
        assert nested.exists()

    def test_empty_specs_returns_empty(self, tmp_path: Path):
        results = generate_charts([], tmp_path)
        assert results == []


class TestConvertChartFormat:
    """Tests for convert_chart_format()."""

    def test_convert_to_svg_from_spec(self, tmp_path: Path):
        results = generate_charts([_bar_spec()], tmp_path)
        r = results[0]
        svg_path = tmp_path / f"{r.chart_id}.svg"
        out = convert_chart_format(Path(r.path), "svg", svg_path)
        assert out == svg_path
        content = svg_path.read_text()
        assert content.startswith("<?xml") or "<svg" in content

    def test_convert_to_pdf_from_spec(self, tmp_path: Path):
        results = generate_charts([_bar_spec()], tmp_path)
        r = results[0]
        pdf_path = tmp_path / f"{r.chart_id}.pdf"
        out = convert_chart_format(Path(r.path), "pdf", pdf_path)
        assert out == pdf_path
        assert pdf_path.read_bytes()[:5] == b"%PDF-"

    def test_svg_fallback_when_no_spec(self, tmp_path: Path):
        """When spec JSON is missing, falls back to PNG-in-SVG."""
        results = generate_charts([_line_spec()], tmp_path)
        r = results[0]
        # Remove the spec JSON to force fallback
        spec_json = tmp_path / f"{r.chart_id}.spec.json"
        spec_json.unlink()

        svg_path = tmp_path / f"{r.chart_id}_fallback.svg"
        out = convert_chart_format(Path(r.path), "svg", svg_path)
        assert out == svg_path
        content = svg_path.read_text()
        assert "data:image/png;base64," in content

    def test_pdf_fallback_when_no_spec(self, tmp_path: Path):
        """When spec JSON is missing, falls back to PNG-in-PDF."""
        results = generate_charts([_line_spec()], tmp_path)
        r = results[0]
        spec_json = tmp_path / f"{r.chart_id}.spec.json"
        spec_json.unlink()

        pdf_path = tmp_path / f"{r.chart_id}_fallback.pdf"
        out = convert_chart_format(Path(r.path), "pdf", pdf_path)
        assert out == pdf_path
        assert pdf_path.read_bytes()[:5] == b"%PDF-"

    def test_creates_output_dir_for_conversion(self, tmp_path: Path):
        results = generate_charts([_bar_spec()], tmp_path)
        r = results[0]
        nested = tmp_path / "converted" / "charts"
        svg_path = nested / f"{r.chart_id}.svg"
        convert_chart_format(Path(r.path), "svg", svg_path)
        assert svg_path.exists()
