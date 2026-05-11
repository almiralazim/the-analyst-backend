# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0][0.2.0] - 2026-05-11

### Added

#### Agent Gate — Intelligent Agent Selection

- Rule-based dynamic agent dispatch that skips irrelevant agents based on dataset characteristics
- Question classification engine (comparison, trend, anomaly, distribution, correlation, general)
- Dataset feature detection (temporal columns, categorical richness, numeric density)
- Agent relevance scoring with configurable thresholds (`app/orchestration/agent_relevance.yaml`)
- Gating metrics tracking for observability (agents skipped, reasons, confidence)
- 823+ unit tests for Agent Gate classification and gating logic

#### Intelligent Plan Selection

- Plan selector that chooses optimal execution plans based on question type and data shape
- Integration with Agent Gate for classification-driven plan routing

#### Model Registry and Router

- `app/llm/model_registry.py` — Centralized registry of all supported models with metadata (tier, context window, capabilities)
- `app/llm/model_router.py` — Routes agents to optimal models based on task complexity tier
- `GET /api/v1/models` endpoint for frontend model selection dropdown
- Database migration (`002_add_model_selection`) adding `model_selection` column to pipeline runs

#### Caching Layer

- Redis-backed caching module (`app/cache.py`) for pipeline results, dataset details, and LLM responses
- User-scoped cache keys to prevent cross-tenant data leakage
- Configurable TTLs (1h for results, 5min for datasets, 1h for LLM responses in dev mode)

#### Documentation

- `docs/GETTING_STARTED.md` — End-to-end walkthrough from setup to first analysis
- `docs/API_REFERENCE.md` — Comprehensive frontend integration guide with curl + TypeScript examples
- `SECURITY.md` — Vulnerability reporting policy
- `Makefile` with 20+ development commands (`make help` for full list)

#### Testing

- Agent Gate tests (`tests/test_agent_gate.py`) — 823 test cases
- Gating metrics tests (`tests/test_gating_metrics.py`) — 250 test cases
- Model registry tests (`tests/test_model_registry.py`) — 124 test cases
- Model router tests (`tests/test_model_router.py`) — 169 test cases
- Plan selector tests (`tests/test_plan_selector.py`) — 149 test cases
- Finding normalization tests (`tests/test_finding_normalization.py`) — 150 test cases
- Improved integration test fixtures with proper type hints and rate limit handling

### Changed

- Moved Swagger UI and ReDoc under `/api/v1` prefix (`/api/v1/docs`, `/api/v1/redoc`)
- Extracted result normalization and response building into dedicated `app/services/result_builder.py`
- Refactored DAG resolver to support dynamic agent skipping via Agent Gate
- Updated pipeline schemas to include model selection field
- Improved LLM factory with better provider resolution logic
- Cleaned up unused dependencies in `pyproject.toml`

### Fixed

- User-scoped cache keys preventing cross-tenant data access
- Type safety improvements across API layer
- Rate limit handling in integration tests

### Infrastructure

- Alembic migration `002_add_model_selection` for model selection column
- Orchestration registry (`app/orchestration/registry.py`) for agent metadata
- Relevance map module (`app/orchestration/relevance_map.py`) for feature-to-agent mapping

[0.2.0]: https://github.com/Creacubedusa/the-analyst-backend/compare/v0.1.0...v0.2.0

## [0.1.0][0.1.0] - 2026-05-05

### Added

#### Core Platform

- FastAPI application with async SQLAlchemy ORM and PostgreSQL
- 10-agent DAG pipeline with 7-tier parallel execution
- 4 LLM provider integrations (Anthropic, OpenAI, Google Gemini, Groq)
- Smart model routing: user-selectable models with "auto" mode for tier-based agent-to-model assignment (premium/standard/fast)
- `GET /api/v1/models` endpoint for frontend model selection dropdown
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
- `Makefile` with development commands (setup, dev, test, lint, docker, migrations, seed)
- Redis caching layer: pipeline results (1h TTL), dataset details (5min TTL), LLM responses (dev mode)
- Rate limiting backed by Redis for distributed deployments

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

[0.1.0]: https://github.com/Creacubedusa/the-analyst-backend/releases/tag/v0.1.0
