# syntax=docker/dockerfile:1.7
# Multi-stage Dockerfile for KnowGate FastAPI backend

# === Stage 1: Builder ===
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# System deps for building wheels (asyncpg, psycopg2, cryptography, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install hatch (build backend)
RUN pip install --no-cache-dir hatch

# Copy dependency files
COPY pyproject.toml ./

# Build wheel for the app
RUN hatch build --target wheel

# Install all dependencies via wheel (single source of truth: pyproject.toml)
RUN pip install --no-cache-dir dist/*.whl

# === Stage 2: Runtime ===
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# System deps for runtime (libpq for psycopg2, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --system --gid 1001 knowgate \
    && useradd --system --uid 1001 --gid knowgate --create-home --shell /bin/bash knowgate

WORKDIR /app

# Copy Python deps from builder (everything installed in site-packages)
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy app source
COPY --chown=knowgate:knowgate app/ /app/app/

# Switch to non-root
USER knowgate

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Entrypoint
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
