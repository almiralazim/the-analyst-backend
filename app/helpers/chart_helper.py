"""Chart helper: generate PNG chart images and convert to SVG/PDF.

Uses matplotlib with the Agg backend for server-side rendering.
Follows Storytelling with Data (SWD) methodology: action titles,
minimal gridlines, and a muted color palette.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server-side rendering

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

logger = logging.getLogger(__name__)

# SWD-inspired muted palette
_SWD_PALETTE = [
    "#4e79a7",  # steel blue
    "#f28e2b",  # muted orange
    "#e15759",  # soft red
    "#76b7b2",  # teal
    "#59a14f",  # olive green
    "#edc948",  # gold
    "#b07aa1",  # mauve
    "#ff9da7",  # pink
    "#9c755f",  # brown
    "#bab0ac",  # warm grey
]

_DEFAULT_WIDTH = 1500
_DEFAULT_HEIGHT = 900
_DPI = 150


@dataclass
class ChartSpec:
    """Specification for a single chart to generate."""

    chart_type: Literal["bar", "line", "heatmap"]
    title: str
    data: dict[str, Any]
    x_label: str = ""
    y_label: str = ""


@dataclass
class ChartResult:
    """Metadata about a generated chart image."""

    chart_id: str
    path: str
    title: str
    chart_type: str
    width: int = _DEFAULT_WIDTH
    height: int = _DEFAULT_HEIGHT


def _apply_swd_style(ax: matplotlib.axes.Axes) -> None:
    """Apply Storytelling with Data styling to a matplotlib axes.

    - Action titles (bold, left-aligned)
    - Minimal gridlines (light horizontal only)
    - Muted color palette
    - Clean spines (remove top and right)
    """
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.5)
    ax.spines["left"].set_color("#cccccc")
    ax.spines["bottom"].set_linewidth(0.5)
    ax.spines["bottom"].set_color("#cccccc")

    ax.yaxis.grid(True, linewidth=0.3, color="#e0e0e0", linestyle="-")
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)

    ax.tick_params(
        axis="both",
        which="both",
        length=0,
        labelsize=9,
        labelcolor="#666666",
    )

    if ax.get_title():
        ax.set_title(
            ax.get_title(),
            fontsize=13,
            fontweight="bold",
            loc="left",
            color="#333333",
            pad=12,
        )


def _render_bar(ax: matplotlib.axes.Axes, data: dict) -> None:
    """Render a bar chart on the given axes."""
    labels = data.get("labels", [])
    datasets = data.get("datasets", [])
    if not labels or not datasets:
        raise ValueError("Bar chart requires 'labels' and 'datasets'")

    x = np.arange(len(labels))
    n_datasets = len(datasets)
    bar_width = 0.8 / max(n_datasets, 1)

    for i, ds in enumerate(datasets):
        values = ds.get("values", [])
        offset = (i - n_datasets / 2 + 0.5) * bar_width
        color = _SWD_PALETTE[i % len(_SWD_PALETTE)]
        ax.bar(
            x + offset,
            values,
            bar_width,
            label=ds.get("label", f"Series {i + 1}"),
            color=color,
            edgecolor="none",
        )

    ax.set_xticks(x)
    rotation = 0 if len(labels) <= 8 else 45
    ax.set_xticklabels(labels, rotation=rotation, ha="right")

    if n_datasets > 1:
        ax.legend(
            frameon=False,
            fontsize=9,
            labelcolor="#666666",
        )


def _render_line(ax: matplotlib.axes.Axes, data: dict) -> None:
    """Render a line chart on the given axes."""
    labels = data.get("labels", [])
    datasets = data.get("datasets", [])
    if not labels or not datasets:
        raise ValueError("Line chart requires 'labels' and 'datasets'")

    x = np.arange(len(labels))

    for i, ds in enumerate(datasets):
        values = ds.get("values", [])
        color = _SWD_PALETTE[i % len(_SWD_PALETTE)]
        ax.plot(
            x,
            values,
            color=color,
            linewidth=2,
            marker="o",
            markersize=4,
            label=ds.get("label", f"Series {i + 1}"),
        )

    ax.set_xticks(x)
    rotation = 0 if len(labels) <= 8 else 45
    ax.set_xticklabels(labels, rotation=rotation, ha="right")

    if len(datasets) > 1:
        ax.legend(
            frameon=False,
            fontsize=9,
            labelcolor="#666666",
        )


def _render_heatmap(ax: matplotlib.axes.Axes, data: dict) -> None:
    """Render a heatmap on the given axes."""
    x_labels = data.get("x_labels", [])
    y_labels = data.get("y_labels", [])
    values = data.get("values", [])
    if not x_labels or not y_labels or not values:
        raise ValueError(
            "Heatmap requires 'x_labels', 'y_labels', and 'values'"
        )

    arr = np.array(values, dtype=float)
    im = ax.imshow(arr, aspect="auto", cmap="YlOrRd")

    ax.set_xticks(np.arange(len(x_labels)))
    ax.set_xticklabels(x_labels)
    ax.set_yticks(np.arange(len(y_labels)))
    ax.set_yticklabels(y_labels)

    # Annotate cells with values
    for i in range(len(y_labels)):
        for j in range(len(x_labels)):
            val = arr[i, j]
            text_color = "white" if val > arr.max() * 0.7 else "#333333"
            ax.text(
                j, i, f"{val:.0f}",
                ha="center", va="center",
                fontsize=9, color=text_color,
            )

    ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    # Heatmaps don't use the standard grid
    ax.yaxis.grid(False)


_RENDERERS = {
    "bar": _render_bar,
    "line": _render_line,
    "heatmap": _render_heatmap,
}


def _render_chart(spec: ChartSpec, output_path: Path) -> ChartResult:
    """Render a single chart spec to a PNG file and save its spec JSON."""
    chart_id = str(uuid.uuid4())[:12]
    width_inches = _DEFAULT_WIDTH / _DPI
    height_inches = _DEFAULT_HEIGHT / _DPI

    fig, ax = plt.subplots(figsize=(width_inches, height_inches), dpi=_DPI)

    try:
        renderer = _RENDERERS.get(spec.chart_type)
        if renderer is None:
            raise ValueError(f"Unsupported chart type: {spec.chart_type}")

        ax.set_title(spec.title)
        renderer(ax, spec.data)

        if spec.x_label:
            ax.set_xlabel(
                spec.x_label, fontsize=10, color="#666666", labelpad=8,
            )
        if spec.y_label:
            ax.set_ylabel(
                spec.y_label, fontsize=10, color="#666666", labelpad=8,
            )

        _apply_swd_style(ax)
        fig.tight_layout()

        png_path = output_path / f"{chart_id}.png"
        fig.savefig(str(png_path), dpi=_DPI, bbox_inches="tight")

        # Save the spec as JSON alongside the PNG for re-rendering
        spec_json_path = output_path / f"{chart_id}.spec.json"
        spec_dict = asdict(spec)
        spec_dict["chart_id"] = chart_id
        with open(spec_json_path, "w", encoding="utf-8") as f:
            json.dump(spec_dict, f, indent=2, default=str)

        return ChartResult(
            chart_id=chart_id,
            path=str(png_path),
            title=spec.title,
            chart_type=spec.chart_type,
            width=_DEFAULT_WIDTH,
            height=_DEFAULT_HEIGHT,
        )
    finally:
        plt.close(fig)


def generate_charts(
    specs: list[ChartSpec],
    output_dir: Path,
) -> list[ChartResult]:
    """Generate PNG chart images from a list of specs.

    Each chart is rendered independently. If a single chart fails,
    the error is logged and the chart is skipped — remaining charts
    are still generated.

    A JSON spec file is saved alongside each PNG for later
    re-rendering in other formats (SVG, PDF).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[ChartResult] = []

    for i, spec in enumerate(specs):
        try:
            result = _render_chart(spec, output_dir)
            results.append(result)
        except Exception:
            logger.exception(
                "Chart generation failed for spec %d (%s: %s)",
                i, spec.chart_type, spec.title,
            )

    return results


def _re_render_from_spec(
    spec_data: dict,
    target_format: str,
    output_path: Path,
) -> Path:
    """Re-render a chart from its saved spec JSON in the target format."""
    chart_spec = ChartSpec(
        chart_type=spec_data["chart_type"],
        title=spec_data["title"],
        data=spec_data["data"],
        x_label=spec_data.get("x_label", ""),
        y_label=spec_data.get("y_label", ""),
    )

    width_inches = _DEFAULT_WIDTH / _DPI
    height_inches = _DEFAULT_HEIGHT / _DPI

    fig, ax = plt.subplots(figsize=(width_inches, height_inches), dpi=_DPI)

    try:
        renderer = _RENDERERS.get(chart_spec.chart_type)
        if renderer is None:
            raise ValueError(
                f"Unsupported chart type: {chart_spec.chart_type}"
            )

        ax.set_title(chart_spec.title)
        renderer(ax, chart_spec.data)

        if chart_spec.x_label:
            ax.set_xlabel(
                chart_spec.x_label, fontsize=10,
                color="#666666", labelpad=8,
            )
        if chart_spec.y_label:
            ax.set_ylabel(
                chart_spec.y_label, fontsize=10,
                color="#666666", labelpad=8,
            )

        _apply_swd_style(ax)
        fig.tight_layout()

        fig.savefig(
            str(output_path),
            format=target_format,
            dpi=_DPI,
            bbox_inches="tight",
        )
        return output_path
    finally:
        plt.close(fig)


def _fallback_svg(png_path: Path, output_path: Path) -> Path:
    """Embed a PNG in an SVG wrapper as a fallback."""
    import base64

    png_bytes = png_path.read_bytes()
    b64 = base64.b64encode(png_bytes).decode("ascii")

    svg_content = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{_DEFAULT_WIDTH}" height="{_DEFAULT_HEIGHT}">\n'
        f'  <image width="{_DEFAULT_WIDTH}" height="{_DEFAULT_HEIGHT}" '
        f'xlink:href="data:image/png;base64,{b64}"/>\n'
        f'</svg>\n'
    )

    output_path.write_text(svg_content, encoding="utf-8")
    return output_path


def _fallback_pdf(png_path: Path, output_path: Path) -> Path:
    """Embed a PNG in a single-page PDF as a fallback."""
    from matplotlib.backends.backend_pdf import PdfPages

    img = plt.imread(str(png_path))
    height, width = img.shape[:2]
    fig_w = width / _DPI
    fig_h = height / _DPI

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=_DPI)
    try:
        ax.imshow(img)
        ax.axis("off")
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        with PdfPages(str(output_path)) as pdf:
            pdf.savefig(fig, dpi=_DPI)

        return output_path
    finally:
        plt.close(fig)


def convert_chart_format(
    png_path: Path,
    target_format: Literal["svg", "pdf"],
    output_path: Path,
) -> Path:
    """Convert a chart to SVG or PDF format.

    Strategy:
    1. Look for a ``{chart_id}.spec.json`` next to the PNG.
    2. If found, re-render the chart natively in the target format
       using matplotlib — this produces vector-quality output.
    3. If the spec is missing, fall back to embedding the PNG in an
       SVG wrapper or a single-page PDF.

    Returns the path to the converted file.
    """
    png_path = Path(png_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Derive the spec JSON path from the PNG filename
    chart_id = png_path.stem
    spec_json_path = png_path.parent / f"{chart_id}.spec.json"

    if spec_json_path.exists():
        try:
            with open(spec_json_path, "r", encoding="utf-8") as f:
                spec_data = json.load(f)
            return _re_render_from_spec(spec_data, target_format, output_path)
        except Exception:
            logger.exception(
                "Re-render from spec failed for %s, falling back to "
                "PNG embedding",
                chart_id,
            )

    # Fallback: embed the PNG
    if target_format == "svg":
        return _fallback_svg(png_path, output_path)
    else:
        return _fallback_pdf(png_path, output_path)
