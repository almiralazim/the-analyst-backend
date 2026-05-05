"""Results endpoints: findings, charts, narrative, export."""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.dataset import Dataset
from app.models.pipeline import AgentExecution, PipelineRun
from app.models.result import AnalysisResult
from app.models.user import User
from app.rate_limit import limiter
from app.services.auth import get_current_user

router = APIRouter(prefix="/results", tags=["results"])


async def _get_pipeline_with_results(
    pipeline_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> tuple[PipelineRun, list[AnalysisResult]]:
    """Load a pipeline and its results, verifying ownership."""
    pipe_result = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.id == pipeline_id, PipelineRun.user_id == user_id)
        .options(selectinload(PipelineRun.agent_executions))
    )
    pipeline = pipe_result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Pipeline not found"})

    res_result = await db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.pipeline_run_id == pipeline_id)
        .order_by(AnalysisResult.ordering)
    )
    results = res_result.scalars().all()
    return pipeline, results


@router.get(
    "/{pipeline_id}",
    summary="Get full analysis results for a pipeline",
    response_description="Complete analysis results including findings, charts, narrative, and validation",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Pipeline not found or not owned by user", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Pipeline not found"}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def get_results(
    request: Request,
    pipeline_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get the complete analysis results for a finished pipeline.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `pipeline_id` (UUID, required): The pipeline's unique identifier.

    **Response (200):**
    ```json
    {
      "data": {
        "pipeline_id": "uuid",
        "question": "What drove revenue growth in Q4?",
        "status": "completed",
        "confidence_grade": "A",
        "confidence_score": 0.92,
        "duration_ms": 95000,
        "findings": [
          {
            "headline": "Revenue grew 23% driven by enterprise segment",
            "detail": "Enterprise deals increased by...",
            "impact": "high",
            "confidence": 0.95,
            "sources": ["sales_data.orders"]
          }
        ],
        "charts": [
          {
            "id": "chart-uuid",
            "title": "Revenue by Segment",
            "type": "bar",
            "url": "/api/v1/results/{pipeline_id}/charts/{chart_id}",
            "width": 1500,
            "height": 900
          }
        ],
        "narrative": {
          "executive_summary": "...",
          "detailed_findings": "...",
          "recommendations": [...]
        },
        "validation": {
          "structural": {"status": "pass", "checks": 12, "failures": 0},
          "logical": {"status": "pass", "checks": 8, "failures": 0},
          "business_rules": {"status": "warn", "checks": 5, "failures": 1},
          "simpsons_paradox": {"status": "pass"},
          "overall_grade": "A",
          "overall_score": 0.92
        },
        "agent_summary": [
          {"agent": "data_explorer", "status": "completed", "duration_ms": 4500}
        ]
      },
      "meta": {
        "dataset_id": "uuid",
        "dataset_name": "Q4 Sales Data",
        "execution_plan": "deep_dive",
        "created_at": "2025-01-15T10:30:00Z",
        "completed_at": "2025-01-15T10:31:35Z"
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Pipeline does not exist or belongs to another user.

    **Frontend Integration:**
    - Only call this after the pipeline `status` is `"completed"`.
    - Use `findings` array to render insight cards with headline, detail, and impact badge.
    - Use `charts[].url` to load chart images (supports PNG, SVG, PDF via format query param).
    - Use `narrative.executive_summary` for the top-level summary section.
    - Use `validation.overall_grade` to show a confidence badge (A/B/C/D/F).
    - The `meta` section provides context about the source dataset and timing.
    """
    pipeline, results = await _get_pipeline_with_results(pipeline_id, user.id, db)

    # Get dataset name
    ds_result = await db.execute(select(Dataset).where(Dataset.id == pipeline.dataset_id))
    dataset = ds_result.scalar_one_or_none()
    dataset_name = dataset.name if dataset else "Unknown"

    # Categorize results
    findings = [r.content for r in results if r.result_type == "finding" and r.content]
    charts = []
    for r in results:
        if r.result_type == "chart" and r.content:
            chart = dict(r.content)
            chart["url"] = f"/api/v1/results/{pipeline_id}/charts/{chart.get('id', r.id)}"
            charts.append(chart)

    narrative_results = [r for r in results if r.result_type == "narrative"]
    narrative = narrative_results[0].content if narrative_results else None

    validation_results = [r for r in results if r.result_type == "validation"]
    validation = validation_results[0].content if validation_results else None

    # Agent summary
    agent_summary = [
        {
            "agent": ae.agent_name,
            "status": ae.status,
            "duration_ms": ae.duration_ms,
        }
        for ae in sorted(pipeline.agent_executions, key=lambda x: (x.tier or 0, x.agent_name))
    ]

    # Compute duration
    duration_ms = None
    if pipeline.started_at and pipeline.completed_at:
        duration_ms = int((pipeline.completed_at - pipeline.started_at).total_seconds() * 1000)

    return {
        "data": {
            "pipeline_id": str(pipeline.id),
            "question": pipeline.question,
            "status": pipeline.status,
            "confidence_grade": pipeline.confidence_grade,
            "confidence_score": pipeline.confidence_score,
            "duration_ms": duration_ms,
            "findings": findings,
            "charts": charts,
            "narrative": narrative,
            "validation": validation,
            "agent_summary": agent_summary,
        },
        "meta": {
            "dataset_id": str(pipeline.dataset_id),
            "dataset_name": dataset_name,
            "execution_plan": pipeline.execution_plan,
            "created_at": pipeline.created_at.isoformat() if pipeline.created_at else None,
            "completed_at": pipeline.completed_at.isoformat() if pipeline.completed_at else None,
        },
    }


@router.get(
    "/{pipeline_id}/findings",
    summary="Get findings only for a pipeline",
    response_description="Array of findings (insights) extracted from the analysis",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Pipeline not found or not owned by user", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Pipeline not found"}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def get_findings(
    request: Request,
    pipeline_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get only the findings (insights) from a completed pipeline.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `pipeline_id` (UUID, required): The pipeline's unique identifier.

    **Response (200):**
    ```json
    {
      "data": [
        {
          "headline": "Revenue grew 23% driven by enterprise segment",
          "detail": "Enterprise deals increased by 45% while SMB remained flat...",
          "impact": "high",
          "confidence": 0.95,
          "supporting_data": {"metric": "revenue", "change": 0.23},
          "sources": ["sales_data.orders", "sales_data.customers"]
        }
      ]
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Pipeline does not exist or belongs to another user.

    **Frontend Integration:**
    - Use this endpoint when you only need findings without charts/narrative (lighter payload).
    - Sort findings by `impact` (high → medium → low) for display priority.
    - Use `confidence` (0-1) to show a confidence indicator per finding.
    - The `sources` array lists which tables/columns were used to derive the finding.
    """
    _, results = await _get_pipeline_with_results(pipeline_id, user.id, db)
    findings = [r.content for r in results if r.result_type == "finding" and r.content]
    return {"data": findings}


_CHART_MEDIA_TYPES = {
    "png": "image/png",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
}


@router.get(
    "/{pipeline_id}/charts/{chart_id}",
    summary="Get a chart image in PNG, SVG, or PDF format",
    response_description="Binary chart image with appropriate Content-Type header",
    responses={
        400: {"description": "Invalid chart format requested", "content": {"application/json": {"example": {"error": {"code": "VALIDATION_ERROR", "message": "Format must be one of: png, svg, pdf"}}}}},
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Pipeline or chart not found", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Chart not found"}}}}},
        500: {"description": "Chart format conversion failed", "content": {"application/json": {"example": {"error": {"code": "CONVERSION_ERROR", "message": "Chart format conversion to svg failed: ..."}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def get_chart(
    request: Request,
    pipeline_id: uuid.UUID,
    chart_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    format: Annotated[str, Query()] = "png",
):
    """Retrieve a specific chart image, optionally converted to SVG or PDF.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `pipeline_id` (UUID, required): The pipeline's unique identifier.
    - `chart_id` (string, required): The chart's identifier (from the results response).

    **Query Parameters:**
    - `format` (string, optional, default="png"): Output format. One of: `png`, `svg`, `pdf`.

    **Response:** Binary image file with appropriate Content-Type header.
    - PNG: `image/png`
    - SVG: `image/svg+xml`
    - PDF: `application/pdf`

    **Response Headers:**
    - `Cache-Control: public, max-age=31536000, immutable` — charts are immutable once generated.
    - `ETag: "<hash>"` — content-based ETag for conditional requests.

    **Errors:**
    - `400 Bad Request`: Invalid format value (must be png, svg, or pdf).
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Pipeline or chart not found.
    - `500 Internal Server Error`: Format conversion failed (SVG/PDF conversion issue).

    **Frontend Integration:**
    - Use the chart URL directly in `<img src="...">` tags for PNG format.
    - Add `?format=svg` for scalable vector graphics (better for responsive layouts).
    - Add `?format=pdf` for print-quality exports.
    - Charts are immutable and aggressively cached — safe to cache indefinitely on the client.
    - Use the `ETag` header for conditional requests (`If-None-Match`) to avoid re-downloads.
    - Include the auth token in the request (use fetch + blob URL pattern for `<img>` tags).

    **Example (loading chart in React):**
    ```javascript
    const res = await fetch(`/api/v1/results/${pipelineId}/charts/${chartId}?format=png`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    // Use `url` as img src, revoke when component unmounts
    ```
    """
    if format not in _CHART_MEDIA_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VALIDATION_ERROR",
                "message": (
                    "Format must be one of: "
                    f"{', '.join(_CHART_MEDIA_TYPES)}"
                ),
            },
        )

    # Verify ownership
    pipe_result = await db.execute(
        select(PipelineRun).where(
            PipelineRun.id == pipeline_id,
            PipelineRun.user_id == user.id,
        )
    )
    if not pipe_result.scalar_one_or_none():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOT_FOUND",
                "message": "Pipeline not found",
            },
        )

    # Look for chart PNG in storage
    chart_dir = settings.storage_path / str(pipeline_id) / "charts"
    chart_path = chart_dir / f"{chart_id}.png"

    if not chart_path.exists():
        # Try dataset-level chart storage
        ds_result = await db.execute(
            select(PipelineRun.dataset_id).where(
                PipelineRun.id == pipeline_id,
            )
        )
        dataset_id = ds_result.scalar_one_or_none()
        if dataset_id:
            chart_path = (
                settings.storage_path
                / str(dataset_id)
                / "charts"
                / f"{chart_id}.png"
            )

    if not chart_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOT_FOUND",
                "message": "Chart not found",
            },
        )

    # For PNG, serve the file directly
    if format == "png":
        content_hash = hashlib.sha256(
            chart_path.read_bytes(),
        ).hexdigest()[:16]
        return FileResponse(
            path=str(chart_path),
            media_type="image/png",
            headers={
                "Cache-Control": (
                    "public, max-age=31536000, immutable"
                ),
                "ETag": f'"{content_hash}"',
            },
        )

    # For SVG or PDF, convert via chart helper
    from app.helpers.chart_helper import convert_chart_format

    target_fmt: Literal["svg", "pdf"] = (
        "svg" if format == "svg" else "pdf"
    )
    output_path = chart_path.parent / f"{chart_id}.{target_fmt}"
    try:
        convert_chart_format(
            chart_path, target_fmt, output_path,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "CONVERSION_ERROR",
                "message": (
                    f"Chart format conversion to {format} failed: "
                    f"{exc}"
                ),
            },
        )

    content_hash = hashlib.sha256(
        output_path.read_bytes(),
    ).hexdigest()[:16]
    return FileResponse(
        path=str(output_path),
        media_type=_CHART_MEDIA_TYPES[format],
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{content_hash}"',
        },
    )


@router.get(
    "/{pipeline_id}/narrative",
    summary="Get narrative text for a pipeline",
    response_description="Executive summary, detailed findings, and recommendations",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Pipeline not found or not owned by user", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Pipeline not found"}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def get_narrative(
    request: Request,
    pipeline_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get only the narrative (executive summary + detailed analysis) from a pipeline.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `pipeline_id` (UUID, required): The pipeline's unique identifier.

    **Response (200):**
    ```json
    {
      "data": {
        "executive_summary": "Revenue grew 23% in Q4, primarily driven by...",
        "detailed_findings": "## Key Drivers\\n\\n1. Enterprise segment...",
        "recommendations": [
          {
            "action": "Increase enterprise sales team headcount",
            "rationale": "Enterprise segment shows 3x ROI vs SMB",
            "confidence": "high",
            "impact": "high"
          }
        ]
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Pipeline does not exist or belongs to another user.

    **Frontend Integration:**
    - `executive_summary` is plain text suitable for a hero section.
    - `detailed_findings` may contain markdown — render with a markdown parser.
    - `recommendations` is a structured array for rendering action cards.
    - Returns `null` for `data` if the pipeline hasn't produced a narrative yet.
    """
    _, results = await _get_pipeline_with_results(pipeline_id, user.id, db)
    narrative_results = [r for r in results if r.result_type == "narrative"]
    narrative = narrative_results[0].content if narrative_results else None
    return {"data": narrative}


@router.get(
    "/{pipeline_id}/export/{fmt}",
    summary="Export analysis results as HTML, PDF, or DOCX",
    response_description="Downloadable document file with Content-Disposition header",
    responses={
        400: {"description": "Invalid export format", "content": {"application/json": {"example": {"error": {"code": "VALIDATION_ERROR", "message": "Format must be one of: html, pdf, docx"}}}}},
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
        404: {"description": "Pipeline not found or not owned by user", "content": {"application/json": {"example": {"error": {"code": "NOT_FOUND", "message": "Pipeline not found"}}}}},
        503: {"description": "Export dependency unavailable (e.g., WeasyPrint for PDF)", "content": {"application/json": {"example": {"error": {"code": "DEPENDENCY_UNAVAILABLE", "message": "PDF export requires WeasyPrint, which is not installed."}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def export_results(
    request: Request,
    pipeline_id: uuid.UUID,
    fmt: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Export the full analysis results as a downloadable document.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Path Parameters:**
    - `pipeline_id` (UUID, required): The pipeline's unique identifier.
    - `fmt` (string, required): Export format. One of: `html`, `pdf`, `docx`.

    **Response:** Binary file download with appropriate Content-Type and Content-Disposition headers.
    - HTML: `text/html` — self-contained HTML document with inline styles.
    - PDF: `application/pdf` — formatted PDF report (requires WeasyPrint on server).
    - DOCX: `application/vnd.openxmlformats-officedocument.wordprocessingml.document`

    **Response Headers:**
    - `Content-Disposition: attachment; filename="analysis_{pipeline_id}.{fmt}"`

    **Errors:**
    - `400 Bad Request`: Invalid format (must be html, pdf, or docx).
    - `401 Unauthorized`: Access token is missing or invalid.
    - `404 Not Found`: Pipeline does not exist or belongs to another user.
    - `503 Service Unavailable`: PDF export requires WeasyPrint which is not installed.

    **Frontend Integration:**
    - Trigger download using fetch + blob pattern:
    ```javascript
    const res = await fetch(`/api/v1/results/${pipelineId}/export/pdf`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `analysis_${pipelineId}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
    ```
    - Show a loading spinner during export — PDF generation can take a few seconds.
    - If 503 is returned for PDF, fall back to HTML export or show a message that PDF is unavailable.
    - HTML export is always available and is the fastest option.
    """
    valid_formats = ("html", "pdf", "docx")
    if fmt not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VALIDATION_ERROR",
                "message": f"Format must be one of: {', '.join(valid_formats)}",
            },
        )

    pipeline, results = await _get_pipeline_with_results(pipeline_id, user.id, db)

    findings = [r.content for r in results if r.result_type == "finding" and r.content]
    narrative_results = [r for r in results if r.result_type == "narrative"]
    narrative: dict = (
        narrative_results[0].content
        if narrative_results and narrative_results[0].content
        else {}
    )

    export_dir = settings.storage_path / str(pipeline_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "html":
        html_content = _build_export_html(pipeline, findings, narrative)
        return HTMLResponse(
            content=html_content,
            headers={
                "Content-Disposition": f'attachment; filename="analysis_{pipeline_id}.html"',
            },
        )

    if fmt == "pdf":
        html_content = _build_export_html(pipeline, findings, narrative)
        pdf_path = export_dir / f"analysis_{pipeline_id}.pdf"
        try:
            from app.services.pdf_exporter import export_to_pdf

            export_to_pdf(html_content, pdf_path)
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "DEPENDENCY_UNAVAILABLE",
                    "message": (
                        "PDF export requires WeasyPrint, which is not installed. "
                        "Install it with: pip install 'ai-analyst-api[pdf]'"
                    ),
                },
            )
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="analysis_{pipeline_id}.pdf"',
            },
        )

    # fmt == "docx"
    from app.services.docx_exporter import export_to_docx

    docx_path = export_dir / f"analysis_{pipeline_id}.docx"
    created_at_str = (
        pipeline.created_at.isoformat() if pipeline.created_at else None
    )
    export_to_docx(
        question=pipeline.question,
        confidence_grade=pipeline.confidence_grade,
        execution_plan=pipeline.execution_plan,
        created_at=created_at_str,
        findings=findings,
        narrative=narrative,
        output_path=docx_path,
    )
    docx_content_type = (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    )
    return FileResponse(
        path=str(docx_path),
        media_type=docx_content_type,
        headers={
            "Content-Disposition": f'attachment; filename="analysis_{pipeline_id}.docx"',
        },
    )


def _build_export_html(pipeline: PipelineRun, findings: list[dict], narrative: dict) -> str:
    """Build a self-contained HTML export document."""
    findings_html = ""
    for f in findings:
        headline = f.get("headline", "Finding")
        detail = f.get("detail", "")
        impact = f.get("impact", "medium")
        findings_html += f"""
        <div class="finding">
            <h3>{headline}</h3>
            <span class="impact impact-{impact}">{impact}</span>
            <p>{detail}</p>
        </div>
        """

    exec_summary = narrative.get("executive_summary", "") if isinstance(narrative, dict) else ""
    detailed = narrative.get("detailed_findings", "") if isinstance(narrative, dict) else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analysis: {pipeline.question[:80]}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 2rem; color: #1a1a1a; }}
        h1 {{ font-size: 1.5rem; border-bottom: 2px solid #2563eb; padding-bottom: 0.5rem; }}
        h2 {{ font-size: 1.2rem; color: #374151; margin-top: 2rem; }}
        .meta {{ color: #6b7280; font-size: 0.9rem; margin-bottom: 2rem; }}
        .grade {{ display: inline-block; padding: 0.25rem 0.75rem; border-radius: 9999px; font-weight: 600; }}
        .finding {{ background: #f9fafb; border-left: 4px solid #2563eb; padding: 1rem; margin: 1rem 0; border-radius: 0 0.5rem 0.5rem 0; }}
        .impact {{ font-size: 0.75rem; padding: 0.125rem 0.5rem; border-radius: 9999px; font-weight: 600; }}
        .impact-high {{ background: #fef2f2; color: #dc2626; }}
        .impact-medium {{ background: #fffbeb; color: #d97706; }}
        .impact-low {{ background: #f0fdf4; color: #059669; }}
        .summary {{ background: #eff6ff; padding: 1.5rem; border-radius: 0.5rem; margin: 1rem 0; }}
    </style>
</head>
<body>
    <h1>{pipeline.question}</h1>
    <div class="meta">
        Confidence: <span class="grade">{pipeline.confidence_grade or 'N/A'}</span>
        &middot; Plan: {pipeline.execution_plan or 'deep_dive'}
        &middot; Generated: {pipeline.created_at.strftime('%Y-%m-%d %H:%M') if pipeline.created_at else 'N/A'}
    </div>
    <div class="summary"><h2>Executive Summary</h2><p>{exec_summary}</p></div>
    <h2>Findings</h2>
    {findings_html}
    <h2>Detailed Analysis</h2>
    <div>{detailed}</div>
</body>
</html>"""
