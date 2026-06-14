---
type: deployment-guide
status: draft
created: 2026-06-14
updated: 2026-06-14
owner: "@seang"
tags: [deployment, know-gate, docker-compose, helm]
links:
  - "[[README.md]]"
  - "[[docs/code-standards.md]]"
  - "[[docs/system-architecture.md]]"
  - "[[docs/codebase-summary.md]]"
changelog:
  - 2026-06-14 | manual | source connectors shipped: listed SYNC_* and MAX_DOC_SIZE_MB env vars; worker + beat already in compose
  - 2026-06-14 | manual | auth shipped: bootstrap first user, magic link, OAuth; updated troubleshooting
  - 2026-06-14 | manual | documented make init, /ready, alembic troubleshooting
  - 2026-06-14 | manual | removed all development-stage wording (docs are system-only)
  - 2026-06-14 | manual | removed references to internal plan files
  - 2026-06-14 | manual | initial deployment guide
---

# KnowGate — Deployment Guide

> Quickstart for local dev (Docker Compose) and pointer to prod (Helm, on the public roadmap).

## 1. Prerequisites

- Docker Engine 24+ and Docker Compose v2.
- 4 CPU, 8 GB RAM minimum (8 CPU, 16 GB recommended for bge-m3 + LLM).
- Free ports: 80, 3000, 4000, 5432, 6333, 6379, 9000, 9001, 8025, 1025.
- `openssl` and `python3` available (for `make secrets`).

## 2. Local Quickstart (Docker Compose)

```bash
# 1. Clone
git clone <repo> know-gate && cd know-gate

# 2. Copy env template
cp .env.example .env

# 3. Generate JWT key pair + 32-byte encryption key
make secrets
# Add the printed KG_ENCRYPTION_KEY=... to your .env

# 4. (Optional) Fill OAuth client IDs, SMTP, OpenAI API key in .env
#    Dev defaults work without these (no OAuth, MailHog catches emails)

# 5. Start all services
make up

# 6. Verify
curl http://localhost:8000/health
open http://localhost:3000
```

Total time: ~5 min for image build on first run; subsequent `make up` < 30s.

## 3. Services & URLs

| Service | Port | URL | Purpose | Notes |
|---------|------|-----|---------|-------|
| API | 8000 | http://localhost:8000 | FastAPI backend | Liveness: `/health`, readiness: `/ready` (PG + Qdrant + Redis + MinIO), OpenAPI: `/docs`, metrics: `/metrics` |
| Frontend | 3000 | http://localhost:3000 | Next.js web UI | Multilingual (VI/EN) |
| LiteLLM | 4000 | http://localhost:4000 | LLM gateway (OpenAI-compatible) | Default model: `gpt-4o-mini` |
| PostgreSQL | 5432 | localhost:5432 | App data + audit | User: `knowgate`, pwd: `knowgate_dev_pwd` |
| Qdrant | 6333 | http://localhost:6333 | Vector store | HTTP; gRPC: 6334 |
| Redis | 6379 | localhost:6379 | Cache + Celery queue | Optional password |
| MinIO | 9000 / 9001 | http://localhost:9001 | S3 object store | Console: `knowgate` / `knowgate_dev_pwd` |
| MailHog | 1025 / 8025 | http://localhost:8025 | SMTP dev catcher | All emails land here |
| Worker | — | — | Celery worker (sync, embed, index) | No public port |
| Beat | — | — | Celery scheduler | No public port |
| Init | — | — | One-shot container: `alembic upgrade head` + Qdrant collection + MinIO bucket + seed | API waits on `service_completed_successfully` |

## 4. Dev Commands

| Command | Purpose |
|---------|---------|
| `make up` | Start all services in background |
| `make down` | Stop all services (volumes preserved) |
| `make logs` | Tail logs from all services |
| `make ps` | List running services with status |
| `make restart` | Restart all services |
| `make build` | Rebuild images |
| `make migrate` | Run Alembic DB migrations (`alembic upgrade head` inside `api` container) |
| `make seed` | Seed default data: admin user, 3 roles, 2 access groups, `system_settings` singleton |
| `make init` | Run infra init only (Qdrant collection + MinIO bucket + seed) — DB schema is handled by `make migrate` |
| `make test` | Run backend tests (pytest) |
| `make lint` | Run linters (ruff + eslint) |
| `make format` | Run formatters (ruff format + prettier) |
| `make secrets` | Generate JWT key pair + encryption key |
| `make clean` | Remove all containers + volumes (DESTRUCTIVE) |
| `make cli-install` | Install CLI in editable mode (when CLI is added) |

## 5. Environment Variables

All env vars are listed in `.env.example` with comments. Highlights:

- **Required:** `DB_*`, `REDIS_*`, `QDRANT_*`, `MINIO_*`, `JWT_*`, `KG_ENCRYPTION_KEY`.
- **Optional (dev defaults work):** `OPENAI_API_KEY`, `GOOGLE_OAUTH_*`, `GITHUB_OAUTH_*`, `SMTP_*` (MailHog catches emails in dev).
- **Source sync (optional, defaults work):** `SYNC_INTERVAL_MINUTES` (default 5 — Celery Beat poll cadence), `SYNC_MAX_CONCURRENT` (default 3 — max concurrent sync jobs per instance), `SYNC_BATCH_SIZE` (default 100), `MAX_DOC_SIZE_MB` (default 50 — docs above this are skipped with a warning).
- **Atomic granularity:** never use a long connection URL — each component is split into `HOST`, `PORT`, `USER`, `PASSWORD`, `NAME`.

Compose fails fast on missing required vars (`${VAR:?VAR required}`).

## 6. Troubleshooting

### Port already in use
Edit `.env` to change the port for the conflicting service (e.g. `DB_PORT=5433`, `QDRANT_PORT=6335`).

### `alembic upgrade` fails
Most common: Postgres is not yet healthy, or env vars are missing. Check:
1. `make ps` — `kg-postgres` should be `(healthy)`. Wait 10-20s after `make up` on first run.
2. `make logs init` — see the full error from the init container.
3. Verify `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` in `.env` match `kg-postgres` (default host is `localhost` for host-side, `postgres` for in-network).
4. If the schema is already partially applied, `make migrate` from scratch: `make clean && make up`.

### API not ready (after `make up`)
Run `make logs api` to see startup errors. Common causes:
- Missing `KG_ENCRYPTION_KEY` (run `make secrets`).
- Database not yet healthy (wait 10-20s after `make up`).
- Stale `secrets/` directory (regenerate with `make secrets`).

### Drive push notifications never arrive
Drive `changes.watch` requires a publicly reachable HTTPS endpoint on `POST /api/v1/webhooks/google-drive`. In local dev use a tunnel (e.g. `ngrok http 8000` or `cloudflared`) and update the public URL on the source; the polling fallback every 5 min still catches changes. Production must terminate TLS in front of the API.

### OAuth fails at login
Dev mode logs in via `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` (default `admin@knowgate.local` / `ChangeMe123!`) — no OAuth needed for first test. To enable OAuth, fill `GOOGLE_OAUTH_*` or `GITHUB_OAUTH_*` in `.env` and restart.

### LLM calls fail with 401
Set `OPENAI_API_KEY` in `.env` (when LLM is wired). Or run Ollama locally and set `OLLAMA_BASE_URL` for self-hosted fallback.

### Reset everything
```bash
make clean   # removes all containers + volumes
make up      # fresh start
```

### Reset only the database
```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml down -v postgres
make up
```

## 7. Production Deployment (Helm, planned)

Compose is dev + single-host self-host only. For K8s production:

- Targets: HA Postgres (operator or managed), Qdrant cluster, Redis Sentinel, S3 (or MinIO distributed), 3+ API replicas, 2+ worker replicas, 1 Beat (leader), Nginx Ingress, cert-manager, OTel collector to Grafana Cloud or self-hosted Loki/Prometheus/Grafana.
- Config swap, not rewrite: same `KG_*` / `DB_*` / `REDIS_*` / `QDRANT_*` env vars; just supplied via K8s Secrets + ConfigMap.
- Helm chart is on the public roadmap (not yet shipped).

## 8. CI/CD

CI runs on every push to `main` and on PRs. See `.github/workflows/ci.yml`:

1. Backend lint (ruff check + format check).
2. Backend test (pytest with test env vars).
3. Frontend lint (eslint + tsc --noEmit + prettier).
4. Frontend build (next build).
5. Docker validate (`docker compose config --quiet`).
6. CI status gate (fails if any job fails).

CI is read-only. No auto-deploy — manual `make up` (dev) or `helm install` (prod, when Helm is shipped).

## 9. See Also

- [[README.md]] — quickstart and dev commands.
- [[docs/code-standards.md]] — env vars, Docker, security patterns.
- [[docs/system-architecture.md]] — service topology.
- [[docs/codebase-summary.md]] — what's in the box.
