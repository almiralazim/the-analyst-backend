# The Analyst API Reference

A complete integration guide for frontend engineers consuming The Analyst Backend API.

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Datasets](#datasets)
4. [Pipelines](#pipelines)
5. [Results](#results)
6. [Knowledge](#knowledge)
7. [Error Handling](#error-handling)
8. [WebSocket Protocol](#websocket-protocol)
9. [Rate Limits](#rate-limits)

---

## Overview

### Base URL

```text
http://localhost:8000/api/v1
```

Production deployments will use HTTPS. All endpoints are prefixed with `/api/v1`.

### Authentication Method

All endpoints (except registration, login, refresh, and health checks) require a Bearer token:

```text
Authorization: Bearer <access_token>
```

Tokens are JWTs issued by the `/auth/register` and `/auth/login` endpoints.

### Response Envelope

All successful responses use a consistent wrapper:

```json
{
  "data": { ... }
}
```

Paginated responses include metadata:

```json
{
  "data": [ ... ],
  "meta": {
    "total": 42,
    "page": 1,
    "page_size": 20
  }
}
```

### Content Type

- Request bodies: `application/json` (except file uploads which use `multipart/form-data`)
- Responses: `application/json` (except chart images and file exports)

### Interactive Documentation

- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`
- OpenAPI JSON: `GET /openapi.json`

---

## Authentication

### POST /auth/register

Register a new user account and receive authentication tokens.

**Auth required:** No

**Request Body:**

| Field | Type | Required | Description |
| ------- | ------ | ---------- | ------------- |
| `email` | string | Yes | Valid email address. Must be unique. |
| `password` | string | Yes | 8-128 characters. |
| `display_name` | string | No | Display name, max 100 characters. |

**Response (201):**

```json
{
  "data": {
    "user": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "email": "analyst@example.com",
      "display_name": "Jane Doe",
      "role": "user",
      "preferences": {},
      "created_at": "2025-01-15T10:30:00Z"
    },
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 3600
  }
}
```

**Error Responses:**

| Status | Code | Description |
| -------- | ------ | ------------- |
| 409 | `CONFLICT` | Email already registered |
| 422 | Validation | Invalid email format or password too short |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "analyst@example.com",
    "password": "securepass123",
    "display_name": "Jane Doe"
  }'
```

**TypeScript example:**

```typescript
const response = await fetch('/api/v1/auth/register', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: 'analyst@example.com',
    password: 'securepass123',
    display_name: 'Jane Doe',
  }),
});

const { data } = await response.json();
// Store data.access_token in memory (not localStorage)
// Store data.refresh_token in HttpOnly cookie or secure storage
```

---

### POST /auth/login

Authenticate with email and password.

**Auth required:** No

**Request Body:**

| Field | Type | Required | Description |
| ------- | ------ | ---------- | ------------- |
| `email` | string | Yes | Registered email address |
| `password` | string | Yes | Account password |

**Response (200):**

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

**Error Responses:**

| Status | Code | Description |
| -------- | ------ | ------------- |
| 401 | `UNAUTHORIZED` | Invalid email or password |
| 422 | Validation | Missing required fields |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "analyst@example.com", "password": "securepass123"}'
```

**TypeScript example:**

```typescript
const response = await fetch('/api/v1/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'analyst@example.com', password: 'securepass123' }),
});

if (response.status === 401) {
  // Show generic "Invalid credentials" message
}

const { data } = await response.json();
```

---

### POST /auth/refresh

Exchange a valid refresh token for a new access token.

**Auth required:** No (uses refresh_token in body)

**Request Body:**

| Field | Type | Required | Description |
| ------- | ------ | ---------- | ------------- |
| `refresh_token` | string | Yes | Valid refresh token from login/register |

**Response (200):**

```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "expires_in": 3600
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 401 | `UNAUTHORIZED` | Invalid or expired refresh token |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJhbGciOiJIUzI1NiIs..."}'
```

**TypeScript example:**

```typescript
async function refreshAccessToken(refreshToken: string): Promise<string> {
  const response = await fetch('/api/v1/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (response.status === 401) {
    // Refresh token expired — redirect to login
    throw new Error('Session expired');
  }

  const { data } = await response.json();
  return data.access_token;
}
```

---

### GET /auth/me

Get the current authenticated user's profile.

**Auth required:** Yes

**Response (200):**

```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "analyst@example.com",
    "display_name": "Jane Doe",
    "role": "user",
    "preferences": {},
    "created_at": "2025-01-15T10:30:00Z"
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 401 | `UNAUTHORIZED` | Missing or invalid access token |

**curl example:**

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

**TypeScript example:**

```typescript
const response = await fetch('/api/v1/auth/me', {
  headers: { Authorization: `Bearer ${accessToken}` },
});

if (response.status === 401) {
  // Token expired — trigger refresh flow
}

const { data: user } = await response.json();
```

---

## Datasets

### POST /datasets

Upload one or more data files to create a new dataset.

**Auth required:** Yes

**Content-Type:** `multipart/form-data`

**Form Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `files` | File[] | Yes | Data files (.csv, .tsv, .xlsx, .xls). Max 10 files. |
| `name` | string | Yes | Human-readable dataset name |
| `description` | string | No | Description of the dataset |

**Limits:**
- Max files per upload: 10
- Max individual file size: 500 MB
- Max total upload size: 1 GB

**Response (201):**

```json
{
  "data": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "Q4 Sales Data",
    "description": "Regional sales for Q4 2024",
    "source_type": "csv",
    "status": "ready",
    "table_count": 3,
    "total_rows": 15000,
    "schema_profile": {
      "tables": [
        {
          "name": "sales",
          "columns": [
            {"name": "id", "type": "INTEGER"},
            {"name": "revenue", "type": "DOUBLE"},
            {"name": "date", "type": "DATE"}
          ],
          "row_count": 5000
        }
      ]
    },
    "created_at": "2025-01-15T10:30:00Z",
    "updated_at": "2025-01-15T10:30:05Z"
  }
}
```

**Dataset Status Lifecycle:**

```
uploading → profiling → ready (success)
uploading → profiling → error (profiling failed)
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `VALIDATION_ERROR` | Unsupported file type or too many files |
| 413 | `PAYLOAD_TOO_LARGE` | File or total upload exceeds size limits |
| 422 | Validation | Missing required form fields |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/datasets \
  -H "Authorization: Bearer $TOKEN" \
  -F "name=Q4 Sales Data" \
  -F "description=Regional sales for Q4 2024" \
  -F "files=@sales.csv" \
  -F "files=@customers.csv"
```

**TypeScript example:**

```typescript
const formData = new FormData();
formData.append('name', 'Q4 Sales Data');
formData.append('description', 'Regional sales for Q4 2024');
formData.append('files', salesFile);
formData.append('files', customersFile);

const response = await fetch('/api/v1/datasets', {
  method: 'POST',
  headers: { Authorization: `Bearer ${token}` },
  body: formData,
  // Do NOT set Content-Type — let the browser set the multipart boundary
});

const { data: dataset } = await response.json();
```

---

### GET /datasets

List all datasets owned by the authenticated user.

**Auth required:** Yes

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number (1-indexed) |
| `page_size` | int | 20 | Items per page |

**Response (200):**

```json
{
  "data": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "name": "Q4 Sales Data",
      "source_type": "csv",
      "status": "ready",
      "table_count": 3,
      "total_rows": 15000,
      "created_at": "2025-01-15T10:30:00Z"
    }
  ],
  "meta": {
    "total": 5,
    "page": 1,
    "page_size": 20
  }
}
```

**curl example:**

```bash
curl "http://localhost:8000/api/v1/datasets?page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch(`/api/v1/datasets?page=${page}&page_size=20`, {
  headers: { Authorization: `Bearer ${token}` },
});

const { data: datasets, meta } = await response.json();
const totalPages = Math.ceil(meta.total / meta.page_size);
```

---

### GET /datasets/{dataset_id}

Get full details for a specific dataset including schema profile.

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `dataset_id` | UUID | Dataset identifier |

**Response (200):**

```json
{
  "data": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "Q4 Sales Data",
    "description": "Regional sales for Q4 2024",
    "source_type": "csv",
    "status": "ready",
    "table_count": 3,
    "total_rows": 15000,
    "schema_profile": {
      "tables": [
        {
          "name": "sales",
          "columns": [
            {"name": "id", "type": "INTEGER"},
            {"name": "revenue", "type": "DOUBLE"},
            {"name": "region", "type": "VARCHAR"},
            {"name": "date", "type": "DATE"}
          ],
          "row_count": 5000
        }
      ]
    },
    "created_at": "2025-01-15T10:30:00Z",
    "updated_at": "2025-01-15T10:30:05Z"
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 404 | `NOT_FOUND` | Dataset not found or not owned by user |

**curl example:**

```bash
curl http://localhost:8000/api/v1/datasets/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch(`/api/v1/datasets/${datasetId}`, {
  headers: { Authorization: `Bearer ${token}` },
});

const { data: dataset } = await response.json();
// Use dataset.schema_profile.tables to render table explorer
```

---

### GET /datasets/{dataset_id}/tables/{table_name}/preview

Preview rows from a specific table within a dataset.

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `dataset_id` | UUID | Dataset identifier |
| `table_name` | string | Table name (from schema_profile) |

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number (1-indexed) |
| `page_size` | int | 50 | Rows per page (max recommended: 100) |

**Response (200):**

```json
{
  "data": {
    "columns": ["id", "name", "revenue", "date"],
    "rows": [
      [1, "Widget A", 1500.00, "2024-10-01"],
      [2, "Widget B", 2300.50, "2024-10-02"]
    ],
    "total_rows": 5000,
    "page": 1,
    "page_size": 50
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 404 | `NOT_FOUND` | Dataset not found or DuckDB file unavailable |

**curl example:**

```bash
curl "http://localhost:8000/api/v1/datasets/$DATASET_ID/tables/sales/preview?page=1&page_size=50" \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch(
  `/api/v1/datasets/${datasetId}/tables/${tableName}/preview?page=${page}&page_size=50`,
  { headers: { Authorization: `Bearer ${token}` } }
);

const { data } = await response.json();
// data.columns = ["id", "name", "revenue", "date"]
// data.rows = [[1, "Widget A", 1500.00, "2024-10-01"], ...]
```

---

### DELETE /datasets/{dataset_id}

Permanently delete a dataset and all associated storage.

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `dataset_id` | UUID | Dataset identifier |

**Response (200):**

```json
{
  "data": {
    "success": true
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 404 | `NOT_FOUND` | Dataset not found or not owned by user |

**curl example:**

```bash
curl -X DELETE http://localhost:8000/api/v1/datasets/$DATASET_ID \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch(`/api/v1/datasets/${datasetId}`, {
  method: 'DELETE',
  headers: { Authorization: `Bearer ${token}` },
});

if (response.ok) {
  // Remove dataset from local state and redirect to list
}
```

---

## Models

### GET /models

List available LLM providers and models for the model selection dropdown.

**Auth required:** Yes

**Response (200):**

```json
{
  "data": {
    "options": [
      {
        "value": "auto",
        "label": "Auto (Recommended)",
        "provider": null,
        "description": "Automatically selects the best model for each agent based on task complexity",
        "tier": null
      },
      {
        "value": "anthropic",
        "label": "Anthropic - Claude Sonnet 4",
        "provider": "anthropic",
        "description": "Complex reasoning and analysis",
        "tier": "premium"
      },
      {
        "value": "openai",
        "label": "OpenAI - GPT-4o",
        "provider": "openai",
        "description": "Advanced reasoning and generation",
        "tier": "premium"
      },
      {
        "value": "gemini",
        "label": "Gemini - Gemini 2.5 Pro",
        "provider": "gemini",
        "description": "Balanced reasoning and generation",
        "tier": "standard"
      },
      {
        "value": "groq",
        "label": "Groq - Llama 3.3 70B",
        "provider": "groq",
        "description": "Ultra-fast inference",
        "tier": "fast"
      }
    ],
    "default": "auto",
    "warning": null
  }
}
```

**Notes:**
- Only providers with configured API keys appear in the response.
- Use the `value` field as the `model` parameter when creating a pipeline.
- The `tier` field indicates model capability: "premium" (complex reasoning), "standard" (balanced), "fast" (simple tasks).

**curl example:**

```bash
curl http://localhost:8000/api/v1/models \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch('/api/v1/models', {
  headers: { Authorization: `Bearer ${token}` },
});

const { data } = await response.json();
// data.options — populate a <select> dropdown
// data.default — pre-select this value ("auto")
```

---

## Pipelines

### POST /pipelines

Create and start a new analysis pipeline.

**Auth required:** Yes

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `dataset_id` | UUID | Yes | ID of a dataset with `status: "ready"` |
| `question` | string | Yes | Analytical question (5-2000 characters) |
| `plan` | string | No | Execution plan: `"deep_dive"` (default), `"full_presentation"`, `"validate_only"` |
| `model` | string | No | LLM model: `"auto"` (default), provider name, or model ID. Use `GET /models` for options. |

**Execution Plans:**

| Plan | Description |
|------|-------------|
| `deep_dive` | Full 10-agent pipeline with findings, charts, narrative, and validation |
| `full_presentation` | Same as deep_dive, optimized for presentation output |
| `validate_only` | Runs only validation agents — useful for verifying existing analyses |

**Response (201):**

```json
{
  "data": {
    "id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
    "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "question": "What drove revenue growth in Q4?",
    "execution_plan": "deep_dive",
    "status": "queued",
    "created_at": "2025-01-15T10:30:00Z",
    "agents": []
  }
}
```

**Pipeline Status Lifecycle:**

```
queued → running → completed | failed | cancelled
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `VALIDATION_ERROR` | Dataset exists but is not in "ready" status |
| 404 | `NOT_FOUND` | Dataset not found or not owned by user |
| 422 | Validation | Question too short/long or invalid plan value |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "question": "What drove revenue growth in Q4?",
    "plan": "deep_dive"
  }'
```

**TypeScript example:**

```typescript
const response = await fetch('/api/v1/pipelines', {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    dataset_id: datasetId,
    question: 'What drove revenue growth in Q4?',
    plan: 'deep_dive',
  }),
});

const { data: pipeline } = await response.json();
// Immediately connect to WebSocket for real-time progress
connectWebSocket(pipeline.id, token);
```

---

### GET /pipelines

List all pipeline runs for the authenticated user.

**Auth required:** Yes

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number (1-indexed) |
| `page_size` | int | 20 | Items per page |

**Response (200):**

```json
{
  "data": [
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
      "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "question": "What drove revenue growth in Q4?",
      "complexity": "moderate",
      "execution_plan": "deep_dive",
      "status": "completed",
      "confidence_grade": "A",
      "confidence_score": 0.92,
      "started_at": "2025-01-15T10:30:01Z",
      "completed_at": "2025-01-15T10:31:45Z",
      "agents": [
        {"name": "data_explorer", "tier": 1, "status": "completed", "duration_ms": 4500}
      ],
      "created_at": "2025-01-15T10:30:00Z"
    }
  ],
  "meta": {"total": 15, "page": 1, "page_size": 20}
}
```

**curl example:**

```bash
curl "http://localhost:8000/api/v1/pipelines?page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch(`/api/v1/pipelines?page=${page}&page_size=20`, {
  headers: { Authorization: `Bearer ${token}` },
});

const { data: pipelines, meta } = await response.json();
```

---

### GET /pipelines/{pipeline_id}

Get the current status and details of a specific pipeline.

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `pipeline_id` | UUID | Pipeline identifier |

**Response (200):**

```json
{
  "data": {
    "id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
    "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "question": "What drove revenue growth in Q4?",
    "complexity": "moderate",
    "execution_plan": "deep_dive",
    "status": "running",
    "started_at": "2025-01-15T10:30:01Z",
    "agents": [
      {"name": "data_explorer", "tier": 1, "status": "completed", "duration_ms": 4500},
      {"name": "hypothesis_generator", "tier": 2, "status": "running"}
    ],
    "created_at": "2025-01-15T10:30:00Z"
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 404 | `NOT_FOUND` | Pipeline not found or not owned by user |

**curl example:**

```bash
curl http://localhost:8000/api/v1/pipelines/$PIPELINE_ID \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
// Polling pattern (use WebSocket for real-time updates instead)
async function pollPipeline(pipelineId: string, token: string) {
  const response = await fetch(`/api/v1/pipelines/${pipelineId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const { data } = await response.json();

  if (data.status === 'completed') {
    // Fetch results
  } else if (data.status === 'failed') {
    // Show error_message
  } else {
    // Poll again in 3-5 seconds
    setTimeout(() => pollPipeline(pipelineId, token), 4000);
  }
}
```

---

### POST /pipelines/{pipeline_id}/cancel

Cancel a pipeline that is currently queued or running.

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `pipeline_id` | UUID | Pipeline identifier |

**Response (200) — Successfully cancelled:**

```json
{
  "data": {"success": true, "status": "cancelled"}
}
```

**Response (200) — Already finished (no-op):**

```json
{
  "data": {"success": false, "status": "completed", "message": "Pipeline already finished"}
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 404 | `NOT_FOUND` | Pipeline not found or not owned by user |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/pipelines/$PIPELINE_ID/cancel \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch(`/api/v1/pipelines/${pipelineId}/cancel`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${token}` },
});

const { data } = await response.json();
if (data.success) {
  // Pipeline cancelled — update UI state
}
```

---

### WebSocket: /pipelines/{pipeline_id}/ws

Real-time pipeline progress via WebSocket. See [WebSocket Protocol](#websocket-protocol) section for full details.

---

## Results

### GET /results/{pipeline_id}

Get the complete analysis results for a finished pipeline.

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `pipeline_id` | UUID | Pipeline identifier |

**Response (200):**

```json
{
  "data": {
    "pipeline_id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
    "question": "What drove revenue growth in Q4?",
    "status": "completed",
    "confidence_grade": "A",
    "confidence_score": 0.92,
    "duration_ms": 95000,
    "findings": [
      {
        "headline": "Revenue grew 23% driven by enterprise segment",
        "detail": "Enterprise deals increased by 45% while SMB remained flat...",
        "impact": "high",
        "confidence": 0.95,
        "supporting_data": {"metric": "revenue", "change": 0.23},
        "sources": ["sales_data.orders", "sales_data.customers"]
      }
    ],
    "charts": [
      {
        "id": "chart-uuid",
        "title": "Revenue by Segment",
        "type": "bar",
        "url": "/api/v1/results/b2c3d4e5-.../charts/chart-uuid",
        "width": 1500,
        "height": 900,
        "agent": "chart_maker"
      }
    ],
    "narrative": {
      "executive_summary": "Revenue grew 23% in Q4...",
      "detailed_findings": "## Key Drivers\n\n1. Enterprise segment...",
      "recommendations": [
        {
          "action": "Increase enterprise sales team headcount",
          "rationale": "Enterprise segment shows 3x ROI vs SMB",
          "confidence": "high",
          "impact": "high"
        }
      ]
    },
    "validation": {
      "structural": {"status": "pass", "checks": 12, "failures": 0, "warnings": 0},
      "logical": {"status": "pass", "checks": 8, "failures": 0, "warnings": 0},
      "business_rules": {"status": "warn", "checks": 5, "failures": 1, "warnings": 1},
      "simpsons_paradox": {"status": "pass", "checked_combinations": 15, "paradoxes_found": 0},
      "overall_grade": "A",
      "overall_score": 0.92,
      "warnings": [
        {"layer": "business_rules", "message": "Revenue metric uses gross not net", "severity": "medium"}
      ]
    },
    "agent_summary": [
      {"agent": "data_explorer", "status": "completed", "duration_ms": 4500},
      {"agent": "hypothesis_generator", "status": "completed", "duration_ms": 8200}
    ]
  },
  "meta": {
    "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "dataset_name": "Q4 Sales Data",
    "execution_plan": "deep_dive",
    "created_at": "2025-01-15T10:30:00Z",
    "completed_at": "2025-01-15T10:31:35Z"
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 401 | `UNAUTHORIZED` | Missing or invalid access token |
| 404 | `NOT_FOUND` | Pipeline not found or not owned by user |

**curl example:**

```bash
curl http://localhost:8000/api/v1/results/$PIPELINE_ID \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch(`/api/v1/results/${pipelineId}`, {
  headers: { Authorization: `Bearer ${token}` },
});

const { data, meta } = await response.json();
// data.findings — render insight cards
// data.charts — load chart images
// data.narrative.executive_summary — hero section
// data.validation.overall_grade — confidence badge
```

---

### GET /results/{pipeline_id}/findings

Get only the findings (insights) from a completed pipeline.

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `pipeline_id` | UUID | Pipeline identifier |

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

**curl example:**

```bash
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/findings \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch(`/api/v1/results/${pipelineId}/findings`, {
  headers: { Authorization: `Bearer ${token}` },
});

const { data: findings } = await response.json();
// Sort by impact: high → medium → low
const sorted = findings.sort((a, b) => impactOrder[a.impact] - impactOrder[b.impact]);
```

---

### GET /results/{pipeline_id}/charts/{chart_id}

Retrieve a specific chart image, optionally converted to SVG or PDF.

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `pipeline_id` | UUID | Pipeline identifier |
| `chart_id` | string | Chart identifier (from results response) |

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `format` | string | `"png"` | Output format: `png`, `svg`, or `pdf` |

**Response:** Binary image file with appropriate Content-Type:
- `image/png` for PNG
- `image/svg+xml` for SVG
- `application/pdf` for PDF

**Response Headers:**
- `Cache-Control: public, max-age=31536000, immutable`
- `ETag: "<content-hash>"`

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `VALIDATION_ERROR` | Invalid format value |
| 404 | `NOT_FOUND` | Pipeline or chart not found |
| 500 | `CONVERSION_ERROR` | SVG/PDF conversion failed |

**curl example:**

```bash
# PNG (default)
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/charts/$CHART_ID \
  -H "Authorization: Bearer $TOKEN" \
  --output chart.png

# SVG
curl "http://localhost:8000/api/v1/results/$PIPELINE_ID/charts/$CHART_ID?format=svg" \
  -H "Authorization: Bearer $TOKEN" \
  --output chart.svg
```

**TypeScript example:**

```typescript
// Load chart as blob URL for <img> tag
async function loadChart(pipelineId: string, chartId: string, format = 'png') {
  const response = await fetch(
    `/api/v1/results/${pipelineId}/charts/${chartId}?format=${format}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  const blob = await response.blob();
  return URL.createObjectURL(blob);
  // Remember to URL.revokeObjectURL() when component unmounts
}
```

---

### GET /results/{pipeline_id}/narrative

Get only the narrative (executive summary + detailed analysis).

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `pipeline_id` | UUID | Pipeline identifier |

**Response (200):**

```json
{
  "data": {
    "executive_summary": "Revenue grew 23% in Q4, primarily driven by...",
    "detailed_findings": "## Key Drivers\n\n1. Enterprise segment...",
    "recommendations": [
      {
        "id": "rec-uuid",
        "action": "Increase enterprise sales team headcount",
        "rationale": "Enterprise segment shows 3x ROI vs SMB",
        "confidence": "high",
        "impact": "high",
        "owner": null,
        "deadline": null
      }
    ]
  }
}
```

**curl example:**

```bash
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/narrative \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const response = await fetch(`/api/v1/results/${pipelineId}/narrative`, {
  headers: { Authorization: `Bearer ${token}` },
});

const { data: narrative } = await response.json();
// narrative.executive_summary — plain text for hero section
// narrative.detailed_findings — markdown, render with a markdown parser
// narrative.recommendations — structured array for action cards
```

---

### GET /results/{pipeline_id}/export/{fmt}

Export the full analysis results as a downloadable document.

**Auth required:** Yes

**Path Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `pipeline_id` | UUID | Pipeline identifier |
| `fmt` | string | Export format: `html`, `pdf`, or `docx` |

**Response:** Binary file download.

| Format | Content-Type | Notes |
|--------|-------------|-------|
| `html` | `text/html` | Self-contained HTML with inline styles |
| `pdf` | `application/pdf` | Requires WeasyPrint on server |
| `docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | Word document |

**Response Headers:**
- `Content-Disposition: attachment; filename="analysis_{pipeline_id}.{fmt}"`

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `VALIDATION_ERROR` | Invalid format (must be html, pdf, or docx) |
| 404 | `NOT_FOUND` | Pipeline not found or not owned by user |
| 503 | `DEPENDENCY_UNAVAILABLE` | PDF export requires WeasyPrint (not installed) |

**curl example:**

```bash
curl http://localhost:8000/api/v1/results/$PIPELINE_ID/export/pdf \
  -H "Authorization: Bearer $TOKEN" \
  --output analysis.pdf
```

**TypeScript example:**

```typescript
async function exportResults(pipelineId: string, format: 'html' | 'pdf' | 'docx') {
  const response = await fetch(`/api/v1/results/${pipelineId}/export/${format}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (response.status === 503) {
    // PDF unavailable — fall back to HTML
    return exportResults(pipelineId, 'html');
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `analysis_${pipelineId}.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}
```

---

## Knowledge

### POST /knowledge/corrections

Record a correction that the system should learn from.

**Auth required:** Yes

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `dataset_id` | UUID | No | Dataset this correction applies to |
| `severity` | string | Yes | `"critical"`, `"high"`, `"medium"`, or `"low"` |
| `category` | string | Yes | See categories below |
| `description` | string | Yes | What was wrong (10-5000 chars) |
| `sql_before` | string | No | The incorrect SQL |
| `sql_after` | string | No | The corrected SQL |
| `prevention_rule` | string | No | Rule to prevent this error (max 2000 chars) |

**Correction Categories:**
`join_error`, `filter_missing`, `metric_definition`, `column_misuse`, `date_handling`, `aggregation_error`, `policy_violation`, `factual_error`, `other`

**Response (201):**

```json
{
  "data": {
    "id": "c3d4e5f6-a7b8-9012-cdef-345678901234",
    "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "severity": "high",
    "category": "join_error",
    "description": "The query joined orders to customers on the wrong key...",
    "sql_before": "SELECT ... FROM orders JOIN customers ON orders.id = customers.id",
    "sql_after": "SELECT ... FROM orders JOIN customers ON orders.customer_id = customers.id",
    "prevention_rule": "Always join orders to customers using orders.customer_id",
    "created_at": "2025-01-15T10:30:00Z"
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 401 | `UNAUTHORIZED` | Missing or invalid access token |
| 422 | Validation | Invalid severity, category, or description too short |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/corrections \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "severity": "high",
    "category": "join_error",
    "description": "The query joined orders to customers on the wrong key, using orders.id instead of orders.customer_id",
    "sql_before": "SELECT * FROM orders JOIN customers ON orders.id = customers.id",
    "sql_after": "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id",
    "prevention_rule": "Always join orders to customers using orders.customer_id"
  }'
```

**TypeScript example:**

```typescript
const response = await fetch('/api/v1/knowledge/corrections', {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    dataset_id: datasetId,
    severity: 'high',
    category: 'join_error',
    description: 'The query joined orders to customers on the wrong key...',
    sql_before: 'SELECT * FROM orders JOIN customers ON orders.id = customers.id',
    sql_after: 'SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id',
    prevention_rule: 'Always join orders to customers using orders.customer_id',
  }),
});

const { data: correction } = await response.json();
```

---

### GET /knowledge/corrections

List all corrections with optional filters.

**Auth required:** Yes

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `severity` | string | — | Filter: `critical`, `high`, `medium`, `low` |
| `category` | string | — | Filter by category |
| `dataset_id` | UUID | — | Filter by dataset |
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Items per page |

**Response (200):**

```json
{
  "data": [
    {
      "id": "c3d4e5f6-a7b8-9012-cdef-345678901234",
      "dataset_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "severity": "high",
      "category": "join_error",
      "description": "...",
      "sql_before": "...",
      "sql_after": "...",
      "prevention_rule": "...",
      "created_at": "2025-01-15T10:30:00Z"
    }
  ],
  "meta": {"total": 8, "page": 1, "page_size": 20}
}
```

**curl example:**

```bash
# All corrections
curl "http://localhost:8000/api/v1/knowledge/corrections" \
  -H "Authorization: Bearer $TOKEN"

# Filtered by severity and dataset
curl "http://localhost:8000/api/v1/knowledge/corrections?severity=high&dataset_id=$DATASET_ID" \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const params = new URLSearchParams();
if (severity) params.set('severity', severity);
if (category) params.set('category', category);
if (datasetId) params.set('dataset_id', datasetId);
params.set('page', String(page));

const response = await fetch(`/api/v1/knowledge/corrections?${params}`, {
  headers: { Authorization: `Bearer ${token}` },
});

const { data: corrections, meta } = await response.json();
```

---

### POST /knowledge/learnings

Record a learning that enriches the system's knowledge.

**Auth required:** Yes

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `category` | string | Yes | See categories below |
| `content` | string | Yes | The learning content (10-5000 chars) |
| `source` | string | No | Where this learning came from (max 255 chars) |

**Learning Categories:**
`data_patterns`, `query_techniques`, `business_context`, `stakeholder_preferences`, `visualization_insights`, `methodology_notes`

**Response (201):**

```json
{
  "data": {
    "id": "d4e5f6a7-b8c9-0123-def4-567890123456",
    "category": "business_context",
    "content": "Revenue is recognized at point of delivery, not at order placement",
    "source": "CFO feedback on Q4 analysis",
    "created_at": "2025-01-15T10:30:00Z"
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 401 | `UNAUTHORIZED` | Missing or invalid access token |
| 422 | Validation | Invalid category or content too short |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/learnings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "category": "business_context",
    "content": "Revenue is recognized at point of delivery, not at order placement",
    "source": "CFO feedback on Q4 analysis"
  }'
```

**TypeScript example:**

```typescript
const response = await fetch('/api/v1/knowledge/learnings', {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    category: 'business_context',
    content: 'Revenue is recognized at point of delivery, not at order placement',
    source: 'CFO feedback on Q4 analysis',
  }),
});

const { data: learning } = await response.json();
```

---

### GET /knowledge/learnings

List all learnings with optional category filter.

**Auth required:** Yes

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `category` | string | — | Filter by category |
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Items per page |

**Response (200):**

```json
{
  "data": [
    {
      "id": "d4e5f6a7-b8c9-0123-def4-567890123456",
      "category": "business_context",
      "content": "Revenue is recognized at point of delivery...",
      "source": "CFO feedback on Q4 analysis",
      "created_at": "2025-01-15T10:30:00Z"
    }
  ],
  "meta": {"total": 12, "page": 1, "page_size": 20}
}
```

**curl example:**

```bash
curl "http://localhost:8000/api/v1/knowledge/learnings?category=business_context" \
  -H "Authorization: Bearer $TOKEN"
```

**TypeScript example:**

```typescript
const params = new URLSearchParams();
if (category) params.set('category', category);
params.set('page', String(page));

const response = await fetch(`/api/v1/knowledge/learnings?${params}`, {
  headers: { Authorization: `Bearer ${token}` },
});

const { data: learnings, meta } = await response.json();
```

---

## Error Handling

### Standard Error Response Shape

All API errors follow this consistent format:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description of what went wrong"
  }
}
```

### Validation Errors (422)

Pydantic validation errors use FastAPI's default format:

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    }
  ]
}
```

### Common Error Codes

| HTTP Status | Code | Meaning |
|-------------|------|---------|
| 400 | `VALIDATION_ERROR` | Request data is invalid |
| 401 | `UNAUTHORIZED` | Missing, invalid, or expired token |
| 403 | `FORBIDDEN` | Authenticated but not authorized for this resource |
| 404 | `NOT_FOUND` | Resource does not exist or is not owned by user |
| 409 | `CONFLICT` | Resource already exists (e.g., duplicate email) |
| 413 | `PAYLOAD_TOO_LARGE` | File or request body exceeds size limits |
| 429 | `RATE_LIMITED` | Too many requests — check `Retry-After` header |
| 500 | `INTERNAL_ERROR` | Unexpected server error |
| 503 | `DEPENDENCY_UNAVAILABLE` | Required service/library not available |

### Frontend Error Handling Pattern

```typescript
async function apiRequest<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      Authorization: `Bearer ${getAccessToken()}`,
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (response.status === 401) {
    // Try token refresh
    const newToken = await refreshAccessToken();
    if (newToken) {
      // Retry with new token
      return apiRequest(url, options);
    }
    // Redirect to login
    redirectToLogin();
    throw new Error('Session expired');
  }

  if (response.status === 429) {
    const retryAfter = response.headers.get('Retry-After');
    throw new RateLimitError(Number(retryAfter) || 60);
  }

  if (!response.ok) {
    const body = await response.json();
    const error = body.error || body.detail;
    throw new ApiError(response.status, error);
  }

  return response.json();
}
```

---

## WebSocket Protocol

### Connection URL

```
ws://<host>/api/v1/pipelines/{pipeline_id}/ws?token=<access_token>
```

Authentication is via the `token` query parameter (since WebSocket doesn't support custom headers in the browser).

### Connection Flow

1. Client connects with a valid access token as query parameter.
2. Server validates the token and verifies pipeline ownership.
3. On success, the connection is accepted and events stream in real-time.
4. Server sends keepalive pings every 30 seconds.

### Event Types

#### agent_started

Fired when an agent begins execution.

```json
{
  "event": "agent_started",
  "agent": "data_explorer",
  "tier": 1,
  "timestamp": "2025-01-15T10:30:01Z"
}
```

#### agent_completed

Fired when an agent finishes successfully.

```json
{
  "event": "agent_completed",
  "agent": "data_explorer",
  "duration_ms": 4500,
  "timestamp": "2025-01-15T10:30:05Z"
}
```

#### agent_failed

Fired when an agent encounters an error.

```json
{
  "event": "agent_failed",
  "agent": "hypothesis_generator",
  "error": "LLM rate limit exceeded",
  "timestamp": "2025-01-15T10:30:10Z"
}
```

#### pipeline_completed

Fired when the entire pipeline finishes successfully.

```json
{
  "event": "pipeline_completed",
  "pipeline_id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
  "confidence_grade": "A",
  "duration_ms": 95000,
  "timestamp": "2025-01-15T10:31:35Z"
}
```

#### pipeline_failed

Fired when the pipeline fails or is cancelled.

```json
{
  "event": "pipeline_failed",
  "pipeline_id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
  "error": "Critical agent failure at tier 1",
  "failed_at_tier": 1,
  "timestamp": "2025-01-15T10:30:15Z"
}
```

#### ping

Server keepalive sent every 30 seconds.

```json
{
  "event": "ping",
  "timestamp": "2025-01-15T10:30:30Z"
}
```

### Close Codes

| Code | Meaning |
|------|---------|
| 4001 | Authentication failed (missing/invalid/expired token) |
| 4003 | Forbidden (pipeline belongs to another user) |
| 4004 | Pipeline not found |

### Frontend Integration Example

```typescript
function connectPipelineWebSocket(pipelineId: string, token: string) {
  const wsUrl = `ws://${window.location.host}/api/v1/pipelines/${pipelineId}/ws?token=${token}`;
  const ws = new WebSocket(wsUrl);

  let reconnectAttempts = 0;
  const maxReconnectDelay = 30000;

  ws.onopen = () => {
    reconnectAttempts = 0;
    console.log('WebSocket connected');
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    switch (data.event) {
      case 'agent_started':
        updateAgentStatus(data.agent, 'running');
        break;
      case 'agent_completed':
        updateAgentStatus(data.agent, 'completed', data.duration_ms);
        break;
      case 'agent_failed':
        updateAgentStatus(data.agent, 'failed', undefined, data.error);
        break;
      case 'pipeline_completed':
        handlePipelineComplete(data.confidence_grade, data.duration_ms);
        ws.close();
        break;
      case 'pipeline_failed':
        handlePipelineFailed(data.error);
        ws.close();
        break;
      case 'ping':
        // Keepalive — no action needed
        break;
    }
  };

  ws.onclose = (event) => {
    if (event.code === 4001) {
      // Token expired — refresh and reconnect
      refreshTokenAndReconnect(pipelineId);
      return;
    }

    if (event.code !== 1000) {
      // Unexpected close — reconnect with exponential backoff
      const delay = Math.min(1000 * 2 ** reconnectAttempts, maxReconnectDelay);
      reconnectAttempts++;
      setTimeout(() => connectPipelineWebSocket(pipelineId, token), delay);
    }
  };

  return ws;
}
```

### Reconnection Strategy

| Attempt | Delay |
|---------|-------|
| 1 | 1 second |
| 2 | 2 seconds |
| 3 | 4 seconds |
| 4 | 8 seconds |
| 5 | 16 seconds |
| 6+ | 30 seconds (max) |

If the close code is `4001` (auth failed), refresh the access token before reconnecting.

---

## Rate Limits

### Per-Endpoint Limits

| Endpoint Category | Rate Limit | Notes |
|-------------------|-----------|-------|
| Auth endpoints | 60/minute | Per IP |
| Dataset upload | 10/minute | Heavy operation |
| Pipeline creation | 10/minute | Heavy operation |
| All other endpoints | 60/minute | Per user |

### 429 Response

When rate-limited, the API returns:

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Rate limit exceeded: 60 per 1 minute"
  }
}
```

**Response Headers:**
- `Retry-After: <seconds>` — How long to wait before retrying.

### Frontend Handling

```typescript
class RateLimitError extends Error {
  constructor(public retryAfter: number) {
    super(`Rate limited. Retry after ${retryAfter} seconds.`);
  }
}

// In your API client:
if (response.status === 429) {
  const retryAfter = parseInt(response.headers.get('Retry-After') || '60', 10);
  // Option 1: Auto-retry after delay
  await new Promise(resolve => setTimeout(resolve, retryAfter * 1000));
  return retryRequest(url, options);

  // Option 2: Show user feedback
  showToast(`Too many requests. Please wait ${retryAfter} seconds.`);
}
```

### Best Practices

- Implement client-side request deduplication to avoid redundant calls.
- Use optimistic UI updates to reduce the need for immediate re-fetches.
- Cache responses where appropriate (dataset lists, completed results).
- For pipeline progress, prefer WebSocket over polling to reduce request volume.
- Batch operations where possible (e.g., upload multiple files in one request).
