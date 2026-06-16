# KnowGate Backend

FastAPI backend for KnowGate — RAG-based, multilingual, permission-aware knowledge search.

Part of the [KnowGate monorepo](../README.md). See the project root README for full quickstart, service map, and architecture.

## Stack

- **Python 3.12**, FastAPI, Pydantic v2
- **PostgreSQL 16** + SQLAlchemy 2 (async) + Alembic
- **Qdrant** for vector search
- **Redis** for cache and Celery broker
- **Celery** worker + beat for async indexing and scheduled jobs
- **LiteLLM** as the LLM gateway (OpenAI-compatible)
- **MinIO** (S3-compatible) for object storage
- **structlog** + **OpenTelemetry** + **Prometheus** for observability

## Local development

The recommended way to run the backend is via the root `make up` (Docker Compose). For pure backend iteration without containers:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Point at a local Postgres / Redis / Qdrant / MinIO (see .env.example)
export $(grep -v '^#' ../.env | xargs)
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another terminal, start the Celery worker:

```bash
celery -A app.celery_app worker --loglevel=INFO --concurrency=2
```

## Tests

```bash
cd backend
make test            # or: pytest
make lint            # ruff + mypy
```

Coverage threshold is enforced at 80% (see `pyproject.toml` `[tool.pytest.ini_options]`).

## Project layout

```
backend/
├── app/
│   ├── api/          # FastAPI routers (v1)
│   ├── audit/        # Audit log
│   ├── auth/         # JWT, OAuth, password hashing
│   ├── config.py     # Pydantic settings (env-only, no fallbacks)
│   ├── db/           # SQLAlchemy session, base model
│   ├── indexing/     # Document parsing, chunking, embedding
│   ├── retrieval/    # RAG pipeline: retrieve → rerank → generate
│   ├── sources/      # Source connectors (Google Drive, S3, upload)
│   ├── storage/      # S3/MinIO client
│   ├── worker/       # Celery app + tasks
│   └── main.py       # FastAPI app factory
├── alembic/          # DB migrations
├── tests/            # pytest suite
├── scripts/          # One-off scripts (init, seed, etc.)
├── pyproject.toml
└── Dockerfile
```

## Environment variables

All configuration comes from environment variables. **No hardcoded values, no fallbacks** — the app fails fast with a clear error if a required env var is missing. See `../.env.example` for the full list.

Atomic components only — never a single connection URL:
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_API_KEY`
- `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`

## License

MIT — see [../LICENSE](../LICENSE).
