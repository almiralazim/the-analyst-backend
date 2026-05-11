# Getting Started — End-to-End Guide

A step-by-step walkthrough of The Analyst platform, from first setup to retrieving validated analysis results.

---

## Table of Contents

- [Getting Started — End-to-End Guide](#getting-started--end-to-end-guide)
  - [Table of Contents](#table-of-contents)
  - [Prerequisites](#prerequisites)
  - [Setup \& Launch](#setup--launch)
  - [Step 1: Authenticate](#step-1-authenticate)
    - [Login](#login)
    - [Token Lifecycle](#token-lifecycle)
    - [Register a New User (Optional)](#register-a-new-user-optional)
  - [Step 2: Upload a Dataset](#step-2-upload-a-dataset)
  - [Step 3: Explore the Schema](#step-3-explore-the-schema)
    - [View Dataset Detail](#view-dataset-detail)
    - [Preview Table Data](#preview-table-data)
  - [Step 4: Choose a Model](#step-4-choose-a-model)
    - [List Available Models](#list-available-models)
    - [Model Selection Options](#model-selection-options)
  - [Step 5: Run an Analysis Pipeline](#step-5-run-an-analysis-pipeline)
  - [Step 6: Monitor Progress (WebSocket)](#step-6-monitor-progress-websocket)
    - [Alternative: Poll Status](#alternative-poll-status)
  - [Step 7: Retrieve Results](#step-7-retrieve-results)
    - [Full Results](#full-results)
    - [Findings Only](#findings-only)
    - [Charts](#charts)
    - [Narrative](#narrative)
  - [Step 8: Export Results](#step-8-export-results)
  - [Step 9: Teach the System (Knowledge)](#step-9-teach-the-system-knowledge)
    - [Log a Correction](#log-a-correction)
    - [Add a Learning](#add-a-learning)
  - [Step 10: Run Again (with Learning)](#step-10-run-again-with-learning)
  - [Common Workflows](#common-workflows)
    - [Quick Exploration (Fast + Cheap)](#quick-exploration-fast--cheap)
    - [Deep Analysis (High Quality)](#deep-analysis-high-quality)
    - [Validation Only](#validation-only)
    - [Multiple Datasets](#multiple-datasets)
  - [Troubleshooting](#troubleshooting)
    - [Pipeline Failed](#pipeline-failed)
    - [Upload Failed](#upload-failed)
    - [Authentication Issues](#authentication-issues)
    - [Health Check](#health-check)
  - [API Documentation](#api-documentation)

---

## Prerequisites

- Docker and Docker Compose installed
- At least one LLM API key (Anthropic, OpenAI, Gemini, or Groq)
- A CSV or Excel file to analyze
- curl or any HTTP client (Postman, httpx, fetch)

---

## Setup & Launch

```bash
# Clone the repository
git clone https://github.com/Creacubedusa/the-analyst-backend.git
cd the-analyst-backend

# Configure environment
cp .env.example .env
# Edit .env:
#   - Set SECRET_KEY (generate with: python -c "import secrets; print(secrets.token_urlsafe(64))")
#   - Set POSTGRES_PASSWORD
#   - Set at least one LLM API key (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
#   - Set ADMIN_EMAIL and ADMIN_PASSWORD for the seed user

# Start everything
make up
# Or: docker compose up -d

# Verify it's running
curl http://localhost:8000/health
# → {"status": "ok", "version": "0.1.0", ...}
```

The entrypoint automatically runs database migrations and seeds the admin user on first start.

---

## Step 1: Authenticate

### Login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "password": "YOUR_ADMIN_PASSWORD"
  }'
```

**Response:**

```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 3600
  }
}
```

Save the `access_token` — you'll use it in all subsequent requests:

```bash
export TOKEN="eyJhbGciOiJIUzI1NiIs..."
```

### Token Lifecycle

- Access tokens expire in **60 minutes**
- Refresh tokens expire in **7 days**
- When the access token expires, call `POST /api/v1/auth/refresh` with the refresh token
- All protected endpoints require: `Authorization: Bearer <access_token>`

### Register a New User (Optional)

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "analyst@company.com",
    "password": "SecurePass123!",
    "display_name": "Jane Analyst"
  }'
```

---

## Step 2: Upload a Dataset

Upload one or more CSV/Excel files to create a dataset:

```bash
curl -X POST http://localhost:8000/api/v1/datasets \
  -H "Authorization: Bearer $TOKEN" \
  -F "name=Q4 Sales Data" \
  -F "description=Regional sales for Q4 2024" \
  -F "files=@sales_data.csv"
```

**What happens behind the scenes:**

1. Files are saved to storage
2. Data is loaded into a per-dataset DuckDB database
3. Schema profiling runs (column types, distributions, null rates, FK detection)
4. Status transitions: `uploading` → `profiling` → `ready`

**Response (status: "ready"):**

```json
{
  "data": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "Q4 Sales Data",
    "status": "ready",
    "table_count": 1,
    "total_rows": 15000,
    "schema_profile": {
      "tables": [
        {
          "name": "sales_data",
          "row_count": 15000,
          "columns": [
            {"name": "revenue", "type": "DOUBLE", "min": 10.5, "max": 9999.99, "mean": 245.67},
            {"name": "customer", "type": "VARCHAR", "unique_count": 500},
            {"name": "date", "type": "DATE", "date_range_days": 92}
          ]
        }
      ]
    }
  }
}
```

**Supported formats:** `.csv`, `.tsv`, `.xlsx`, `.xls`
**Limits:** 10 files max, 500MB per file, 1GB total

---

## Step 3: Explore the Schema

### View Dataset Detail

```bash
curl http://localhost:8000/api/v1/datasets/$DATASET_ID \
  -H "Authorization: Bearer $TOKEN"
```

The `schema_profile` tells you:

- Table names and row counts
- Column types (INTEGER, DOUBLE, VARCHAR, DATE, etc.)
- Numeric stats (min, max, mean, median, std, percentiles)
- Categorical value counts (top 20 values)
- Data quality (null rates, completeness)
- Detected foreign key relationships between tables

### Preview Table Data

```bash
curl "http://localhost:8000/api/v1/datasets/$DATASET_ID/tables/sales_data/preview?page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN"
```

Returns actual rows so you can verify the data looks correct before running analysis.

---

## Step 4: Choose a Model

### List Available Models

```bash
curl http://localhost:8000/api/v1/models \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**

```json
{
  "data": {
    "options": [
      {"value": "auto", "label": "Auto (Recommended)", "description": "System picks best model per task"},
      {"value": "anthropic", "label": "Anthropic - Claude Sonnet 4", "tier": "premium"},
      {"value": "openai", "label": "OpenAI - GPT-4o", "tier": "premium"},
      {"value": "gemini", "label": "Gemini - Gemini 2.5 Pro", "tier": "standard"},
      {"value": "groq", "label": "Groq - Llama 3.3 70B", "tier": "fast"}
    ],
    "default": "auto"
  }
}
```

### Model Selection Options

| Value | Behavior |
| ------- | ---------- |
| `"auto"` | Each agent gets the best model for its task (recommended) |
| `"anthropic"` | All agents use Claude Sonnet 4 |
| `"openai"` | All agents use GPT-4o |
| `"gemini"` | All agents use Gemini 2.5 Pro |
| `"groq"` | All agents use Llama 3.3 70B (fastest, cheapest) |
| `"gpt-4o-mini"` | All agents use a specific model ID |

**Tip:** Use `"groq"` for fast iteration during development, `"auto"` for production quality.

---

## Step 5: Run an Analysis Pipeline

```bash
curl -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "question": "What drove revenue growth in Q4 and which customer segments contributed most?",
    "model": "auto",
    "plan": "deep_dive"
  }'
```

**Parameters:**

| Field | Required | Description |
| ------- | ---------- | ------------- |
| `dataset_id` | Yes | UUID of a dataset with status "ready" |
| `question` | Yes | Your analytical question (5-2000 chars) |
| `model` | No | LLM selection (default: "auto") |
| `plan` | No | Execution plan (default: "deep_dive") |

**Response:**

```json
{
  "data": {
    "id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
    "status": "queued",
    "question": "What drove revenue growth in Q4...",
    "execution_plan": "deep_dive"
  }
}
```

The pipeline immediately starts executing in the background. Save the pipeline `id`.

---

## Step 6: Monitor Progress (WebSocket)

Connect to the WebSocket for real-time progress:

```text
ws://localhost:8000/api/v1/pipelines/{pipeline_id}/ws?token={access_token}
```

**Events you'll receive:**

```json
{"event": "pipeline_started", "total_agents": 10, "total_tiers": 7}
{"event": "tier_started", "tier": 0, "agents": ["question-framing", "data-explorer"]}
{"event": "agent_started", "agent": "question-framing", "tier": 0}
{"event": "agent_completed", "agent": "question-framing", "tier": 0, "duration_ms": 3200}
{"event": "agent_completed", "agent": "data-explorer", "tier": 0, "duration_ms": 2800}
{"event": "tier_completed", "tier": 0}
...
{"event": "pipeline_completed", "confidence_grade": "A", "duration_ms": 95000}
```

### Alternative: Poll Status

If WebSocket isn't available, poll the pipeline status:

```bash
curl http://localhost:8000/api/v1/pipelines/$PIPELINE_ID \
  -H "Authorization: Bearer $TOKEN"
```

Check `status`: `"queued"` → `"running"` → `"completed"` or `"failed"`

---

## Step 7: Retrieve Results

### Full Results

```bash
curl http://localhost:8000/api/v1/results/$PIPELINE_ID \
  -H "Authorization: Bearer $TOKEN"
```

**Response structure:**

```json
{
  "data": {
    "pipeline_id": "...",
    "question": "What drove revenue growth in Q4...",
    "status": "completed",
    "confidence_grade": "A",
    "confidence_score": 0.92,
    "duration_ms": 95000,
    "findings": [
      {
        "headline": "Enterprise segment drove 67% of Q4 growth",
        "detail": "Enterprise revenue increased 45% while SMB grew only 3%...",
        "impact": "high",
        "confidence": 0.95,
        "supporting_data": {"metric": "revenue", "change": 0.45}
      }
    ],
    "charts": [
      {
        "id": "chart-uuid",
        "title": "Revenue by Segment",
        "type": "bar",
        "url": "/api/v1/results/.../charts/chart-uuid"
      }
    ],
    "narrative": {
      "executive_summary": "Q4 revenue grew 23%, primarily driven by...",
      "detailed_findings": "## Key Drivers\n\n1. Enterprise segment...",
      "recommendations": [...]
    },
    "validation": {
      "structural": {"status": "pass"},
      "logical": {"status": "pass"},
      "business_rules": {"status": "pass"},
      "simpsons_paradox": {"status": "pass"},
      "overall_grade": "A",
      "overall_score": 0.92
    }
  }
}
```

### Findings Only

```bash
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/findings \
  -H "Authorization: Bearer $TOKEN"
```

### Charts

```bash
# PNG (default)
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/charts/$CHART_ID \
  -H "Authorization: Bearer $TOKEN" --output chart.png

# SVG (vector, for presentations)
curl "http://localhost:8000/api/v1/results/$PIPELINE_ID/charts/$CHART_ID?format=svg" \
  -H "Authorization: Bearer $TOKEN" --output chart.svg

# PDF (for documents)
curl "http://localhost:8000/api/v1/results/$PIPELINE_ID/charts/$CHART_ID?format=pdf" \
  -H "Authorization: Bearer $TOKEN" --output chart.pdf
```

### Narrative

```bash
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/narrative \
  -H "Authorization: Bearer $TOKEN"
```

---

## Step 8: Export Results

Export the full analysis as a downloadable document:

```bash
# HTML (self-contained, works everywhere)
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/export/html \
  -H "Authorization: Bearer $TOKEN" --output analysis.html

# PDF (requires WeasyPrint on server)
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/export/pdf \
  -H "Authorization: Bearer $TOKEN" --output analysis.pdf

# Word document
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/export/docx \
  -H "Authorization: Bearer $TOKEN" --output analysis.docx
```

---

## Step 9: Teach the System (Knowledge)

The system learns from corrections and accumulated knowledge. When you spot an error or want to add context:

### Log a Correction

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/corrections \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "severity": "high",
    "category": "metric_definition",
    "description": "Revenue should exclude refunds and returns",
    "prevention_rule": "Always subtract refunds from gross revenue before analysis"
  }'
```

**Severity levels:** `critical`, `high`, `medium`, `low`

**Categories:** `join_error`, `filter_missing`, `metric_definition`, `column_misuse`, `date_handling`, `aggregation_error`, `policy_violation`, `factual_error`, `other`

### Add a Learning

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/learnings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "category": "business_context",
    "content": "Q3 always shows a seasonal dip due to summer holidays in Europe",
    "source": "CFO feedback"
  }'
```

**Categories:** `data_patterns`, `query_techniques`, `business_context`, `stakeholder_preferences`, `visualization_insights`, `methodology_notes`

---

## Step 10: Run Again (with Learning)

When you run the next pipeline on the same dataset, the system automatically:

1. **Loads corrections** — injected into every agent's prompt as "DO NOT repeat these mistakes"
2. **Loads learnings** — provides business context to agents
3. **Applies prevention rules** — agents see specific guidance on what to avoid

```bash
curl -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "question": "What is the true net revenue trend excluding refunds?",
    "model": "auto"
  }'
```

The correction about refunds will now be applied — the system won't make the same mistake twice.

---

## Common Workflows

### Quick Exploration (Fast + Cheap)

```bash
# Use Groq for fast iteration
curl -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "...", "question": "Give me a quick overview of this data", "model": "groq"}'
```

### Deep Analysis (High Quality)

```bash
# Use auto mode for best quality per task
curl -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "...", "question": "What are the root causes of customer churn?", "model": "auto"}'
```

### Validation Only

```bash
# Just validate existing findings without full re-analysis
curl -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "...", "question": "Validate the Q4 revenue claims", "plan": "validate_only"}'
```

### Multiple Datasets

Upload multiple files in one dataset:

```bash
curl -X POST http://localhost:8000/api/v1/datasets \
  -H "Authorization: Bearer $TOKEN" \
  -F "name=Full Sales Suite" \
  -F "files=@orders.csv" \
  -F "files=@customers.csv" \
  -F "files=@products.xlsx"
```

The system detects relationships between tables (foreign keys) and agents can query across them.

---

## Troubleshooting

### Pipeline Failed

Check the error message:

```bash
curl http://localhost:8000/api/v1/pipelines/$PIPELINE_ID \
  -H "Authorization: Bearer $TOKEN" | jq '.data.error_message'
```

Common causes:

- **"Agent timed out"** — The LLM took too long. Try a faster model (`"groq"`) or simplify the question.
- **"No LLM providers configured"** — Set at least one API key in `.env` and restart.
- **"Rate limit exceeded"** — The LLM provider rate-limited you. Wait and retry, or switch providers.

### Upload Failed

- **413 Payload Too Large** — File exceeds 500MB or total exceeds 1GB.
- **400 Unsupported file type** — Only `.csv`, `.tsv`, `.xlsx`, `.xls` are accepted.
- **Status "error"** — Check `error_message` on the dataset for profiling failures.

### Authentication Issues

- **401 Unauthorized** — Token expired. Call `POST /api/v1/auth/refresh` with your refresh token.
- **403 Forbidden** — You're trying to access another user's resource.

### Health Check

```bash
# Basic liveness
curl http://localhost:8000/health

# Full readiness (checks DB, Redis, storage)
curl http://localhost:8000/health/ready
```

If `health/ready` shows `"degraded"`, check which service is down (PostgreSQL, Redis, or storage).

---

## API Documentation

- **Swagger UI** (interactive): [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc** (readable): [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Full API Reference**: [docs/API_REFERENCE.md](API_REFERENCE.md)
- **OpenAPI JSON**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)
