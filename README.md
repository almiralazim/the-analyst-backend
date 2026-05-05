# The Analyst Backend

A production-ready backend that accepts CSV/Excel uploads, runs a 10-agent analytical pipeline powered by LLMs, and returns validated findings with confidence scoring. The system learns from corrections and accumulated knowledge to improve future analyses.

## Features

- **Multi-agent DAG pipeline** — 10 specialized agents execute in 7 tiers with parallel execution, timeouts, and progress streaming
- **4 LLM providers** — Anthropic, OpenAI, Google Gemini, Groq with automatic retry and exponential backoff
- **DuckDB analytics** — Per-dataset analytical engine with safe SQL execution, validation, and pre-built analytical functions
- **4-layer validation** — Structural, logical, business rules, and Simpson's Paradox checks with A-F confidence grading
- **Chart generation** — Matplotlib/Seaborn charts following Storytelling with Data methodology, exportable as PNG/SVG/PDF
- **Knowledge system** — Corrections and learnings persist across sessions, injected into agent prompts
- **Export** — HTML, PDF (WeasyPrint), and Word (python-docx) report generation
- **Security** — JWT auth, WebSocket ownership verification, rate limiting, structured JSON logging
- **Docker-ready** — Multi-stage Dockerfile, docker-compose with Postgres + Redis, automatic migrations and seeding

## Quick Start

### With Docker (recommended)

```bash
# Clone the repository
git clone https://github.com/<org>/ai-analyst-backend.git
cd ai-analyst-backend

# Copy environment file and configure
cp .env.example .env
# Edit .env — set SECRET_KEY, POSTGRES_PASSWORD, and at least one LLM API key

# Start all services (builds image, runs migrations, seeds admin user)
docker compose up --build -d

# API available at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
# ReDoc at http://localhost:8000/redoc
```

### Without Docker

```bash
# Prerequisites: Python 3.11+, PostgreSQL 16+, Redis, uv

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
uv pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env
# Edit .env with your SECRET_KEY, DATABASE_URL, REDIS_URL, and LLM API keys

# Run database migrations
alembic upgrade head

# Seed the admin user
python -m app.seed

# Start the server
uvicorn main:app --reload --port 8000
```

### First Login

After setup, login with the admin credentials from your `.env`:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "YOUR_ADMIN_PASSWORD"}'
```

## Architecture

```mermaid
graph TD
    subgraph API["API Gateway (FastAPI)"]
        AUTH[Auth]
        DS[Datasets]
        PIP[Pipelines]
        RES[Results]
        KN[Knowledge]
        MW[Rate Limiting · Request ID · CORS]
    end

    subgraph ORCH["Orchestration Engine"]
        DAG[DAG Resolver]
        EXEC[Pipeline Executor]
        WS[WebSocket Progress]
        TO[Timeouts]
    end

    subgraph AGENTS["Agent Layer (10 agents · 7 tiers)"]
        QF[question-framing]
        DE[data-explorer]
        HY[hypothesis]
        ST[source-tieout]
        DA[descriptive-analytics]
        OT[overtime-trend]
        RC[root-cause-investigator]
        VA[validation]
        CM[chart-maker]
        SY[storytelling]
    end

    subgraph HELPERS["Helper Modules"]
        SQL[SQL Helpers]
        ANA[Analytics Helpers]
        VAL[Validation Stack]
        CONF[Confidence Scorer]
        CHT[Chart Helper]
    end

    subgraph LLM["LLM Providers (retry + backoff)"]
        ANT[Anthropic]
        OAI[OpenAI]
        GEM[Gemini]
        GRQ[Groq]
    end

    subgraph DATA["Data & Persistence"]
        PG[(PostgreSQL)]
        DDB[(DuckDB)]
        RD[(Redis)]
        FS[File Storage]
    end

    API --> ORCH
    ORCH --> AGENTS
    AGENTS --> HELPERS
    AGENTS --> LLM
    HELPERS --> DDB
    API --> PG
    API --> RD
    DS --> FS
    CHT --> FS
```

## LLM Providers

Set `LLM_DEFAULT_PROVIDER` in `.env`. At least one API key is required.

| Provider | Env Var | Default Model |
|----------|---------|---------------|
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 |
| OpenAI | `OPENAI_API_KEY` | gpt-4o |
| Google Gemini | `GEMINI_API_KEY` | gemini-2.5-pro |
| Groq | `GROQ_API_KEY` | llama-3.3-70b-versatile |

All providers include automatic retry with exponential backoff on rate limits (429) and server errors (5xx).

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/register` | Register a new user |
| `POST` | `/api/v1/auth/login` | Login and get tokens |
| `POST` | `/api/v1/auth/refresh` | Refresh access token |
| `GET` | `/api/v1/auth/me` | Get current user profile |
| `POST` | `/api/v1/datasets` | Upload CSV/Excel files |
| `GET` | `/api/v1/datasets` | List datasets |
| `GET` | `/api/v1/datasets/:id` | Dataset detail + schema |
| `GET` | `/api/v1/datasets/:id/tables/:name/preview` | Preview table data |
| `DELETE` | `/api/v1/datasets/:id` | Delete dataset |
| `POST` | `/api/v1/pipelines` | Start analysis pipeline |
| `GET` | `/api/v1/pipelines` | List pipelines |
| `GET` | `/api/v1/pipelines/:id` | Pipeline status + agents |
| `POST` | `/api/v1/pipelines/:id/cancel` | Cancel running pipeline |
| `WS` | `/api/v1/pipelines/:id/ws` | Real-time progress events |
| `GET` | `/api/v1/results/:id` | Full results (findings, charts, narrative) |
| `GET` | `/api/v1/results/:id/findings` | Findings only |
| `GET` | `/api/v1/results/:id/charts/:chart_id` | Chart image (PNG/SVG/PDF) |
| `GET` | `/api/v1/results/:id/narrative` | Narrative text |
| `GET` | `/api/v1/results/:id/export/:fmt` | Export (html/pdf/docx) |
| `POST` | `/api/v1/knowledge/corrections` | Log a correction |
| `GET` | `/api/v1/knowledge/corrections` | List corrections |
| `POST` | `/api/v1/knowledge/learnings` | Add a learning |
| `GET` | `/api/v1/knowledge/learnings` | List learnings |
| `GET` | `/health` | Liveness check |
| `GET` | `/health/ready` | Readiness check (DB + storage) |

For detailed request/response shapes, examples, and TypeScript integration code, see [docs/API_REFERENCE.md](docs/API_REFERENCE.md).

## Pipeline Agents

10 agents execute in 7 tiers with parallel execution within each tier:

```text
Tier 0: question-framing, data-explorer        (parallel)
Tier 1: hypothesis, source-tieout              (parallel)
Tier 2: descriptive-analytics, overtime-trend   (parallel)
Tier 3: root-cause-investigator
Tier 4: validation
Tier 5: chart-maker
Tier 6: storytelling
```

Each agent:
1. Renders a prompt template with dataset context and corrections
2. Calls the configured LLM provider (with retry)
3. Parses the structured JSON response
4. Runs helper modules (SQL queries, analytics, chart generation, validation)
5. Stores results in the pipeline context for downstream agents

## DuckDB Query Execution

Agents can execute SQL queries against uploaded datasets during pipeline runs:

- **SQL validation** — Only SELECT statements allowed (DDL/DML rejected via sqlglot parsing)
- **Safe execution** — Read-only connections, configurable timeouts, row limits
- **Analytics functions** — Summary stats, time series, segmentation, correlation, anomaly detection, top-N
- **Query results** — Stored in pipeline context and flow to downstream agents

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run only unit tests (fast)
pytest tests/ -v --ignore=tests/integration

# Run with coverage
pytest tests/ -v --cov=app --cov-report=term-missing
```

## Project Structure

```text
ai-analyst-backend/
├── main.py                        # FastAPI app entry point
├── entrypoint.sh                  # Docker entrypoint (migrations + seed + server)
├── app/
│   ├── config.py                  # Pydantic settings (env vars, validation)
│   ├── database.py                # SQLAlchemy async engine
│   ├── logging_config.py          # Structured JSON logging
│   ├── middleware.py              # Request ID middleware
│   ├── rate_limit.py              # SlowAPI rate limiter
│   ├── seed.py                    # Admin user seeding CLI
│   ├── api/                       # Route handlers
│   │   ├── auth.py                # Register, login, refresh, me
│   │   ├── datasets.py            # Upload, list, detail, preview, delete
│   │   ├── pipelines.py           # Create, list, status, cancel, WebSocket
│   │   ├── results.py             # Results, charts, narrative, export
│   │   └── knowledge.py           # Corrections and learnings
│   ├── orchestration/             # DAG engine
│   │   ├── dag_resolver.py        # Topological sort, tier computation
│   │   ├── executor.py            # Tier-by-tier execution with timeouts
│   │   ├── context.py             # Shared pipeline context
│   │   └── registry.yaml          # Agent definitions and dependencies
│   ├── agents/                    # Agent implementations
│   │   ├── base.py                # BaseAgent class
│   │   ├── implementations.py     # 10 agent classes with run_helpers()
│   │   ├── runner.py              # Agent registry and execution
│   │   └── prompts/               # Prompt templates (one .md per agent)
│   ├── helpers/                   # Analytical modules
│   │   ├── sql_helpers.py         # SQL validation, execution, parsing
│   │   ├── analytics_helpers.py   # Summary stats, time series, segmentation, etc.
│   │   ├── validation_stack.py    # 4-layer validation
│   │   ├── confidence_scorer.py   # Confidence score + grade computation
│   │   └── chart_helper.py        # Chart generation + format conversion
│   ├── services/                  # Business logic
│   │   ├── auth.py                # JWT + password hashing
│   │   ├── file_processing.py     # CSV/Excel → DuckDB loading + profiling
│   │   ├── knowledge_bootstrap.py # Pipeline context initialization
│   │   ├── result_builder.py      # Extract results from agent outputs
│   │   ├── pdf_exporter.py        # HTML → PDF (WeasyPrint)
│   │   └── docx_exporter.py       # Results → Word document
│   ├── llm/                       # LLM provider abstraction
│   │   ├── base.py                # Abstract interface + LLMResponse
│   │   ├── factory.py             # Provider factory
│   │   ├── retry.py               # Tenacity retry decorator
│   │   ├── anthropic_provider.py
│   │   ├── openai_provider.py
│   │   ├── gemini_provider.py
│   │   └── groq_provider.py
│   ├── models/                    # SQLAlchemy ORM models
│   └── schemas/                   # Pydantic request/response schemas
├── alembic/                       # Database migrations
│   └── versions/
│       └── 001_initial_schema.py  # Creates all 7 tables
├── tests/                         # Test suite (pytest)
│   ├── integration/               # API integration tests
│   └── ...                        # Unit tests
├── docs/
│   ├── API_REFERENCE.md           # Frontend integration guide
│   ├── MVP_48H_BACKEND_SPEC.md    # Original MVP specification
│   └── KANKA_AI_ANALYST_ARCHITECTURE.md
├── CONTRIBUTING.md                # Contributor guide
├── LICENSE                        # Apache 2.0
├── pyproject.toml                 # Dependencies + tool config
├── docker-compose.yml             # App + Postgres + Redis
├── Dockerfile                     # Multi-stage build
└── .env.example                   # Environment variable template
```

## Configuration

All configuration is via environment variables (or `.env` file). See [.env.example](.env.example) for the full list.

**Required:**
- `SECRET_KEY` — JWT signing key (min 32 chars, generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"`)
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis connection string
- At least one LLM API key

**Optional (with defaults):**
- `PIPELINE_TIMEOUT_SECONDS` (600) — Max pipeline execution time
- `AGENT_DEFAULT_TIMEOUT_SECONDS` (300) — Per-agent timeout
- `LLM_MAX_RETRIES` (3) — LLM retry attempts
- `RATE_LIMIT_DEFAULT` ("60/minute") — Default API rate limit
- `RATE_LIMIT_HEAVY` ("10/minute") — Upload/pipeline creation limit

## Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **API Reference**: [docs/API_REFERENCE.md](docs/API_REFERENCE.md)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)

## License

[Apache 2.0](LICENSE)
