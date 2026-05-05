# The Analyst Backend — Development Commands
# Usage: make <target>

.PHONY: help install dev up down down-v down-clean build rebuild logs seed migrate test lint format clean

# Default target
help: ## Show this help message
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install: ## Install all dependencies (production + dev)
	uv pip install -e ".[dev]" --python .venv/bin/python

venv: ## Create a virtual environment
	python -m venv .venv
	@echo "Activate with: source .venv/bin/activate"

setup: venv install ## Full local setup (venv + install + env file)
	@test -f .env || cp .env.example .env
	@echo ""
	@echo "Setup complete. Edit .env with your credentials, then run:"
	@echo "  make migrate"
	@echo "  make seed"
	@echo "  make dev"

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

dev: ## Start the development server (hot reload)
	.venv/bin/uvicorn main:app --reload --port 8000

run: ## Start the production server
	.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

up: ## Start all containers in detached mode
	docker compose up -d

down: ## Stop all containers
	docker compose down

down-v: ## Stop containers and remove volumes (deletes database data)
	docker compose down -v

down-clean: ## Stop containers, remove volumes and orphans
	docker compose down -v --remove-orphans

build: ## Build the Docker image
	docker compose build

rebuild: ## Rebuild from scratch (no cache)
	docker compose build --no-cache

logs: ## Tail container logs (all services)
	docker compose logs -f

logs-api: ## Tail only the API container logs
	docker compose logs -f api

restart: ## Restart the API container
	docker compose restart api

ps: ## Show running containers
	docker compose ps

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

migrate: ## Run database migrations
	.venv/bin/alembic upgrade head

migrate-docker: ## Run migrations inside the Docker container
	docker compose exec api alembic upgrade head

seed: ## Seed the admin user (reads ADMIN_EMAIL/ADMIN_PASSWORD from .env)
	.venv/bin/python -m app.seed

seed-docker: ## Seed the admin user inside the Docker container
	docker compose exec api python -m app.seed

db-reset: ## Drop and recreate the database (DESTRUCTIVE)
	@echo "WARNING: This will delete all data. Press Ctrl+C to cancel."
	@sleep 3
	docker compose down -v
	docker compose up -d db redis
	@sleep 3
	docker compose up -d api

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: ## Run all tests
	.venv/bin/python -m pytest tests/ -v

test-unit: ## Run unit tests only (fast)
	.venv/bin/python -m pytest tests/ -v --ignore=tests/integration

test-integration: ## Run integration tests only
	.venv/bin/python -m pytest tests/integration/ -v

test-cov: ## Run tests with coverage report
	.venv/bin/python -m pytest tests/ -v --cov=app --cov-report=term-missing --cov-report=html

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------

lint: ## Run the linter (ruff)
	.venv/bin/ruff check .

format: ## Auto-format code (ruff)
	.venv/bin/ruff check . --fix
	.venv/bin/ruff format .

typecheck: ## Run type checking (mypy)
	.venv/bin/mypy app/

check: lint typecheck test ## Run all checks (lint + typecheck + tests)

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

shell: ## Open a Python shell with app context
	.venv/bin/python -c "from app.config import settings; print(f'Connected: {settings.app_name} v{settings.app_version}')" && .venv/bin/python

docs: ## Open API docs in browser
	@echo "Opening http://localhost:8000/docs"
	@open http://localhost:8000/docs 2>/dev/null || xdg-open http://localhost:8000/docs 2>/dev/null || echo "Visit: http://localhost:8000/docs"

clean: ## Remove build artifacts and caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned."
