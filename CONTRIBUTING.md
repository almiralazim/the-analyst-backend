# Contributing to The Analyst Backend

Thanks for your interest in contributing. This guide covers environment setup, running tests, submitting changes, and the project architecture.

## Development Environment Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 16+
- Redis
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Clone and Install

```bash
git clone https://github.com/Creacubedusa/the-analyst-backend.git
cd the-analyst-backend

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install with dev dependencies (pick one)
uv pip install -e ".[dev]"   # recommended
pip install -e ".[dev]"      # alternative
```

### Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in the required values:

- `SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `DATABASE_URL` — your PostgreSQL connection string
- `REDIS_URL` — your Redis connection string
- At least one LLM provider API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `GROQ_API_KEY`)

### Database Setup

```bash
alembic upgrade head
```

### Start the Server

```bash
uvicorn main:app --reload --port 8000
```

API docs are available at `http://localhost:8000/docs`.

## Running Tests and Linting

### Tests

```bash
pytest tests/ -v
```

For coverage:

```bash
pytest tests/ -v --cov=app --cov-report=term-missing
```

### Linter

```bash
ruff check .
```

Auto-fix issues:

```bash
ruff check . --fix
```

### Type Checking

```bash
mypy app/
```

## Submitting Changes

### Branch Naming

Create a branch from `main` with a descriptive prefix:

- `feat/short-description` — new features
- `fix/short-description` — bug fixes
- `docs/short-description` — documentation changes
- `refactor/short-description` — code restructuring
- `test/short-description` — test additions or fixes

### Commit Messages

Use the [Conventional Commits](https://www.conventionalcommits.org/) format:

```text
<type>: <short summary>

<optional body with more detail>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Examples:

```text
feat: add SVG export for charts
fix: handle timeout in pipeline executor
docs: update API endpoint table in README
```

### Pull Request Process

1. Make sure all tests pass (`pytest tests/ -v`) and the linter is clean (`ruff check .`).
2. Keep PRs focused — one logical change per PR.
3. Write a clear description: what changed, why, and how to test it.
4. PRs require at least one approving review before merge.
5. Address review feedback with new commits (don't force-push during review).

## Project Architecture

The backend is organized into layers, each with a clear responsibility:

```text
the-analyst-backend/
├── main.py                        # FastAPI app entry point, middleware wiring
├── app/
│   ├── config.py                  # Pydantic settings (env vars)
│   ├── database.py                # SQLAlchemy async engine + session factory
│   ├── logging_config.py          # Structured JSON logging setup
│   ├── middleware.py              # Request ID middleware
│   ├── rate_limit.py             # SlowAPI rate limiter setup
│   ├── api/                       # 1. API Gateway
│   │   ├── auth.py               #    Auth routes (register, login, refresh)
│   │   ├── datasets.py           #    Dataset CRUD + file upload
│   │   ├── pipelines.py          #    Pipeline management + WebSocket
│   │   ├── results.py            #    Results, export (HTML/PDF/DOCX), charts
│   │   └── knowledge.py          #    Corrections and learnings
│   ├── orchestration/             # 2. Orchestration
│   │   ├── dag.py                #    DAG resolver (tier ordering)
│   │   └── executor.py           #    Pipeline executor (timeout, progress)
│   ├── agents/                    # 3. Agent Layer
│   │   ├── base.py               #    Base agent class
│   │   ├── implementations.py    #    10 specialized agent implementations
│   │   ├── registry.py           #    Agent registry
│   │   └── prompts/              #    Prompt templates (one .md per agent)
│   ├── helpers/                   # 4. Helper Modules
│   │   ├── validation_stack.py   #    4-layer validation (structural, logical, business, Simpson's)
│   │   ├── confidence_scorer.py  #    Confidence score + grade computation
│   │   └── chart_helper.py       #    Chart generation (matplotlib/seaborn)
│   ├── services/                  # 5. Services
│   │   ├── file_processor.py     #    File upload processing
│   │   ├── pdf_exporter.py       #    PDF export (WeasyPrint)
│   │   └── docx_exporter.py      #    Word export (python-docx)
│   ├── llm/                       # 6. LLM Providers
│   │   ├── base.py               #    Abstract LLM provider interface
│   │   ├── factory.py            #    Provider factory
│   │   ├── retry.py              #    Retry decorator (tenacity, exponential backoff)
│   │   ├── anthropic_provider.py
│   │   ├── openai_provider.py
│   │   ├── gemini_provider.py
│   │   └── groq_provider.py
│   ├── models/                    # 7. Data Layer — SQLAlchemy ORM models
│   └── schemas/                   # 7. Data Layer — Pydantic request/response schemas
├── alembic/                       # Database migrations
├── tests/                         # Test suite (pytest)
│   ├── integration/              #    Integration tests (full API flows)
│   └── ...                       #    Unit tests
├── pyproject.toml                 # Dependencies, tool config (ruff, pytest)
└── docker-compose.yml             # Docker setup (app + Postgres + Redis)
```

### How a Request Flows

1. **API Gateway** — FastAPI routes handle HTTP/WebSocket requests, authenticate users, and validate input.
2. **Orchestration** — The DAG resolver determines agent execution order (7 tiers). The pipeline executor runs agents tier-by-tier with timeout enforcement and progress callbacks.
3. **Agents** — Each of the 10 agents renders a prompt template, calls an LLM provider, parses the response, and optionally runs helper modules (charts, validation, confidence scoring).
4. **LLM Providers** — Abstracted behind a common interface. Calls include automatic retry with exponential backoff on transient failures.
5. **Helpers** — Validation stack checks findings programmatically. Confidence scorer grades results. Chart helper generates PNG visualizations.
6. **Data Layer** — PostgreSQL stores users, datasets, pipelines, and results. DuckDB handles analytical queries on uploaded data. File storage holds uploads and generated charts.

### Key Technologies

| Area           | Technology                               |
| -------------- | ---------------------------------------- |
| Web framework  | FastAPI + Uvicorn                        |
| Database       | PostgreSQL (async via asyncpg) + DuckDB  |
| ORM            | SQLAlchemy 2.0 (async)                   |
| Migrations     | Alembic                                  |
| Cache          | Redis                                    |
| LLM providers  | Anthropic, OpenAI, Google Gemini, Groq   |
| Charts         | matplotlib + seaborn                     |
| Testing        | pytest + pytest-asyncio + Hypothesis     |
| Linting        | Ruff                                     |
| Type checking  | mypy                                     |
