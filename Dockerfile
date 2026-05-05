# ---- Stage 1: Build dependencies ----
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Combine updates and install (use HTTPS for apt — HTTP may be blocked in some Docker networks)
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

# Install dependencies
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /app/.venv/bin/pip install --no-cache-dir .


# ---- Stage 2: Runtime ----
# Use the generic tag to get the latest security patches (e.g., 3.11.x)
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

# Patch OS vulnerabilities at runtime
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && apt-get dist-upgrade -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy code
COPY alembic alembic
COPY alembic.ini .
COPY app app
COPY main.py .
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh

# Create and restrict storage
RUN mkdir -p /app/storage && \
    addgroup --system appgroup && \
    adduser --system --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]