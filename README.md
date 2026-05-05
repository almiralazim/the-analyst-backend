# The Analyst Backend

Backend API for the The Analyst Platform — a system that accepts CSV/Excel uploads, runs a multi-agent analytical pipeline, and returns validated findings with confidence scoring.

## Architecture

```
Layer 2: FastAPI API Gateway (auth, datasets, pipelines, results, knowledge)
Layer 3: Orchestration Engine (DAG resolver, pipeline executor, agent runner)
Layer 4: Agent Layer (10 specialized agents with prompt templates)
Layer 5: Helper Modules (statistics, charts, validation — ported from ai-analyst)
Layer 6: Data + Persistence (PostgreSQL, DuckDB, file storage, knowledge system)
```

## Quick Start

### With Docker (recommended)

```bash
# Copy environment file and set your API keys
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.

# Start all services
docker compose up --build

# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

### Without Docker

```bash
# Prerequisites: Python 3.11+, PostgreSQL 16+, Redis

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env
# Edit .env with your database URL and API keys

# Run database migrations
alembic upgrade head

# Seed the admin user
python -m app.seed

# Start the server
uvicorn main:app --reload --port 8000
```

## LLM Providers

Supports four providers out of the box. Set `LLM_DEFAULT_PROVIDER` in `.env`:

| Provider | Env Var | Models |
|----------|---------|--------|
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 (default) |
| OpenAI | `OPENAI_API_KEY` | gpt-4o |
| Google Gemini | `GEMINI_API_KEY` | gemini-2.5-pro |
| Groq | `GROQ_API_KEY` | llama-3.3-70b-versatile |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/register` | Register |
| `POST` | `/api/v1/auth/login` | Login |
| `POST` | `/api/v1/auth/refresh` | Refresh token |
| `GET` | `/api/v1/auth/me` | Current user |
| `POST` | `/api/v1/datasets` | Upload CSV/Excel |
| `GET` | `/api/v1/datasets` | List datasets |
| `GET` | `/api/v1/datasets/:id` | Dataset detail + schema |
| `GET` | `/api/v1/datasets/:id/tables/:name/preview` | Preview table data |
| `DELETE` | `/api/v1/datasets/:id` | Delete dataset |
| `POST` | `/api/v1/pipelines` | Start analysis |
| `GET` | `/api/v1/pipelines` | List pipelines |
| `GET` | `/api/v1/pipelines/:id` | Pipeline status |
| `POST` | `/api/v1/pipelines/:id/cancel` | Cancel pipeline |
| `WS` | `/api/v1/pipelines/:id/ws` | Real-time progress |
| `GET` | `/api/v1/results/:id` | Full results |
| `GET` | `/api/v1/results/:id/charts/:name` | Chart image (PNG) |
| `GET` | `/api/v1/results/:id/export/:fmt` | Export (html/pdf) |
| `POST` | `/api/v1/knowledge/corrections` | Log correction |
| `GET` | `/api/v1/knowledge/corrections` | List corrections |
| `POST` | `/api/v1/knowledge/learnings` | Add learning |
| `GET` | `/api/v1/knowledge/learnings` | List learnings |
| `GET` | `/health` | Liveness check |
| `GET` | `/health/ready` | Readiness check |

## Pipeline Agents (MVP)

10 agents execute in 7 tiers:

```
Tier 0: question-framing, data-explorer       (parallel)
Tier 1: hypothesis, source-tieout             (parallel)
Tier 2: descriptive-analytics, overtime-trend  (parallel)
Tier 3: root-cause-investigator
Tier 4: validation
Tier 5: chart-maker
Tier 6: storytelling
```

## Testing

```bash
pytest tests/ -v
```

## Project Structure

```
ai-analyst-backend/
├── main.py                    # FastAPI app entry point
├── app/
│   ├── config.py              # Environment configuration
│   ├── database.py            # SQLAlchemy async engine
│   ├── models/                # SQLAlchemy ORM models
│   ├── schemas/               # Pydantic request/response schemas
│   ├── api/                   # Route handlers
│   ├── services/              # Business logic
│   ├── orchestration/         # DAG engine + pipeline executor
│   ├── agents/                # Agent implementations + prompts
│   └── llm/                   # LLM provider abstraction (4 providers)
├── alembic/                   # Database migrations
├── tests/                     # Test suite
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```
