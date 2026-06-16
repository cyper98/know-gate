# syntax=docker/dockerfile:1.7
# Multi-stage Dockerfile for KnowGate FastAPI backend

# === Stage 1: Builder ===
FROM python:3.12-slim AS builder

# NOTE: PIP_NO_CACHE_DIR removed — BuildKit cache mount handles caching
# across builds without bloating the final image.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
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
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install hatch

# Copy dependency files first (changes here invalidate downstream layers)
COPY pyproject.toml README.md ./

# Pre-install heavy ML deps in a dedicated cached layer.
# These dominate install time (~1.5 GB: torch + sentence-transformers + unstructured)
# and rarely change — cache mount makes subsequent builds skip re-downloading.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
      "torch>=2.5.0" \
      "sentence-transformers>=3.2.0" \
      "unstructured[all-docs]>=0.16.0"

# Build wheel for the app (metadata + deps; app/ source copied in runtime stage)
RUN hatch build --target wheel

# Install app wheel — pip sees heavy deps already satisfied and skips them.
# Only lighter deps (FastAPI, SQLAlchemy, qdrant, etc.) need downloading.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install dist/*.whl

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
# Copy alembic config + migration tree (used by `init` and `api` on startup)
COPY --chown=knowgate:knowgate alembic.ini /app/alembic.ini
COPY --chown=knowgate:knowgate alembic/ /app/alembic/
# Copy ops scripts (used by `init` for seed/admin setup)
COPY --chown=knowgate:knowgate scripts/ /app/scripts/

# Switch to non-root
USER knowgate

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Entrypoint
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
