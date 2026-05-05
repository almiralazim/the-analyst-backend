"""PDF export service using WeasyPrint (optional dependency)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def export_to_pdf(html_content: str, output_path: Path | str) -> Path:
    """Convert an HTML string to a PDF file.

    Args:
        html_content: The HTML markup to render as PDF.
        output_path: Destination file path for the generated PDF.

    Returns:
        The resolved output path.

    Raises:
        ImportError: If WeasyPrint is not installed.
        RuntimeError: If PDF generation fails for any reason.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "WeasyPrint is required for PDF export but is not installed. "
            "Install it with: pip install weasyprint"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        HTML(string=html_content).write_pdf(str(output_path))
    except Exception as exc:
        logger.error("PDF generation failed: %s", exc)
        raise RuntimeError(f"PDF generation failed: {exc}") from exc

    return output_path
