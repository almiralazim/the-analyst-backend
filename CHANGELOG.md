# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-05

### Added

#### Core Platform
- FastAPI application with async SQLAlchemy ORM and PostgreSQL
- 10-agent DAG pipeline with 7-tier parallel execution
- 4 LLM provider integrations (Anthropic, OpenAI, Google Gemini, Groq)
- Per-dataset DuckDB analytical engine with safe SQL execution
- JWT authentication with access/refresh token flow
- WebSocket real-time pipeline progress streaming
- Docker Compose setup with Postgres, Redis, and automatic bootstrapping

#### API Endpoints
- Auth: register, login, refresh, me
- Datasets: upload (CSV/Excel), list, detail, table preview, delete
- Pipelines: create, list, status, cancel, WebSocket progress
- Results: full results, findings, charts (PNG/SVG/PDF), narrative, export (HTML/PDF/DOCX)
- Knowledge: corrections CRUD, learnings CRUD with filtering
- Health: liveness and readiness checks

#### Agent Pipeline
- Question Framing agent — structures analytical questions
- Data Explorer agent — profiles datasets with DuckDB queries
- Hypothesis agent — generates testable hypotheses
- Source Tieout agent — validates data integrity
- Descriptive Analytics agent — segmentation and top-N analysis
- Overtime Trend agent — time series and anomaly detection
- Root Cause Investigator agent — dimensional drill-down
- Validation agent — 4-layer programmatic verification
- Chart Maker agent — matplotlib/seaborn chart generation
- Storytelling agent — executive narrative synthesis

#### Helper Modules
- `sql_helpers` — SQL validation (sqlglot), safe read-only execution, timeouts, row limits, EXPLAIN, parse/print round-trip
- `analytics_helpers` — summary statistics, time series aggregation, segmentation, correlation, anomaly detection, top-N analysis
- `validation_stack` — structural, logical, business rules, and Simpson's Paradox checks
- `confidence_scorer` — weighted A-F confidence grading from validation results
- `chart_helper` — bar/line/heatmap PNG generation with SWD styling, SVG/PDF conversion

#### Security & Resilience
- WebSocket pipeline ownership verification (close codes 4003/4004)
- Pipeline execution timeout (configurable, default 600s)
- Per-agent timeout (configurable, default 300s)
- LLM provider retry with exponential backoff + jitter (tenacity)
- API rate limiting via SlowAPI (60/min default, 10/min for heavy endpoints)
- SECRET_KEY validation — rejects insecure defaults, enforces 32+ characters
- No hardcoded credentials — all secrets via environment variables
- Read-only DuckDB connections for query execution

#### Infrastructure
- Multi-stage Dockerfile (builder + runtime) with non-root user
- Alembic initial migration creating all 7 database tables
- `entrypoint.sh` — runs migrations + seeds admin user on container start
- `app/seed.py` — CLI script to create admin user from env vars (idempotent)
- Structured JSON logging with request ID propagation
- Request ID middleware (X-Request-ID header)
- Sensitive data redaction in logs

#### Documentation
- `docs/API_REFERENCE.md` — comprehensive frontend integration guide with curl + TypeScript examples
- `CONTRIBUTING.md` — dev setup, testing, PR process, architecture overview
- `SECURITY.md` — vulnerability reporting policy
- `LICENSE` — Apache 2.0
- Rich OpenAPI documentation on all endpoints (Swagger UI at /docs)

#### Testing
- 241+ unit tests covering orchestration, helpers, agents, middleware, and export
- 29 integration tests covering auth, datasets, pipelines, knowledge, and authorization
- Property-based test infrastructure (Hypothesis)
- Async test client with SQLite type adapters for fast integration testing

### Dependencies
- Python 3.11+
- FastAPI, Uvicorn, SQLAlchemy (async), asyncpg, Alembic
- DuckDB, pandas, numpy, scipy, matplotlib, seaborn
- Anthropic, OpenAI, google-genai, Groq SDKs
- Tenacity, SlowAPI, python-json-logger, sqlglot
- python-docx, Jinja2
- Optional: WeasyPrint (PDF export)

[0.1.0]: https://github.com/<org>/ai-analyst-backend/releases/tag/v0.1.0
