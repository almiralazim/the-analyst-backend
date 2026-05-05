#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Seeding admin user..."
python -m app.seed || true

echo "Starting server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
