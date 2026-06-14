---
type: codebase-summary
status: draft
created: 2026-06-14
updated: 2026-06-14
owner: "@seang"
tags: [codebase-summary, know-gate, monorepo]
links:
  - "[[README.md]]"
  - "[[docs/system-architecture.md]]"
  - "[[docs/project-overview-pdr.md]]"
changelog:
  - 2026-06-14 | manual | source connectors shipped: app/sources (BaseSourceConnector + Google Drive + Notion + sync engine + progress), app/tasks (Celery task + Beat schedule), app/celery_app.py, api/v1/sources.py + webhooks.py, Source model webhook fields
  - 2026-06-14 | manual | auth shipped: 6 endpoints, JWT RS256, argon2id, OAuth Google+GitHub, magic link, RBAC, audit log
  - 2026-06-14 | manual | added app/db, app/vector, app/storage, app/cache, alembic, scripts; 14 SQLAlchemy tables; init container; make init
  - 2026-06-14 | manual | removed all development-stage wording (docs are system-only)
  - 2026-06-14 | manual | removed references to internal planning and brainstorming files
  - 2026-06-14 | manual | initial codebase summary
---

# KnowGate — Codebase Summary

> Current snapshot of the codebase. Generated manually — `repomix` is not installed in this environment; structure verified via `ls`/`find` and direct file reads. Internal implementation trackers are not part of this public repo.

## 1. Monorepo Layout

```
know-gate/                       (root)
├── backend/                     FastAPI Python app
├── frontend/                    Next.js 14 TypeScript app
├── cli/                         Python CLI (placeholder, Typer-based)
├── deploy/                      Docker Compose + LiteLLM config
├── secrets/                     JWT keys (gitignored, generated)
├── docs/                        Project documentation (this folder)
├── .github/workflows/ci.yml     5-job CI pipeline
├── .editorconfig                Editor style config
├── .env / .env.example          Env config (gitignored / template)
├── .gitignore                   Standard ignores
├── Makefile                     Dev commands
├── LICENSE                      MIT
└── README.md                    Quickstart
```

> Note: an internal `plans/` folder (architecture + implementation plan) and a `docs/know-gate/brainstorms/` folder (Vietnamese-language BA notes) are kept on the maintainer's local machine but are not pushed to this public repo.

## 2. Backend (`backend/`)

Python 3.12, FastAPI 0.115, managed via `pyproject.toml` + `pip`/`uv`.

| File / dir | Purpose |
|------------|---------|
| `pyproject.toml` | Single source of deps + tool config (ruff, mypy strict, pytest) |
| `Dockerfile` | Multi-stage: builder (hatch) → runtime (slim, non-root UID 1001, healthcheck) |
| `.dockerignore` | Excludes `.venv`, `.pytest_cache`, etc. from build context |
| `app/__init__.py` | Package marker |
| `app/main.py` | FastAPI app, lifespan, CORS, metrics middleware, `ClientIPMiddleware`, `/health`, `/ready` (4-backend parallel check, 2s timeout each, 200 or 503), `/metrics`, `/api/v1`, auth router mounted at `/api/v1/auth` |
| `app/config.py` | Pydantic v2 `Settings`, atomic env vars, computed URLs, encryption key validator |
| `app/logging.py` | structlog JSON (prod) + console (dev), bridges stdlib logging |
| `app/db/` | SQLAlchemy 2 async ORM, session factory, 14-table model registry (users, roles, user_roles, access_groups, user_groups, documents, document_groups, chunks, sources, sync_jobs, queries, feedback, audit_log, system_settings) |
| `app/db/models/` | One file per model: `User`, `Role`, `UserRole`, `AccessGroup`, `UserGroup`, `Document`, `DocumentGroup`, `Chunk`, `Source`, `SyncJob`, `Query`, `Feedback`, `AuditLog`, `SystemSettings` (plus `Base` with `TimestampMixin`, `UUIDPrimaryKeyMixin`, naming convention) |
| `app/db/enums.py` | Enum types (user status, doc status, sync status, etc.) |
| `app/db/session.py` | Async session factory + `check_connection()` for `/ready` |
| `app/vector/` | Qdrant async client (lazy singleton), `chunks` collection init with HNSW (m=16, ef_construct=100) + `group_ids` payload index, indexer + payload schema helpers |
| `app/storage/` | boto3 S3 client pointed at MinIO, `documents` bucket init with versioning, uploader helpers |
| `app/cache/` | Redis async client, JSON get/set/del with TTL, sliding-window rate limit, OAuth state, JTI revocation, magic-link token store, hot-queries sorted set, key naming convention |
| `app/auth/` | Auth + RBAC: `jwt.py` (RS256 mint/verify, 15-min access + 30-day refresh, jti, rotation), `password.py` (argon2id hash/verify/rehash, OWASP 2024 params), `oauth.py` (Authlib AsyncOAuth2Client, Google + GitHub providers, PKCE, state-in-Redis CSRF), `magic_link.py` (32-byte token, SHA-256 at rest, 15-min TTL, one-shot in Redis), `permissions.py` (`Permission` enum, `ROLE_PERMISSIONS` map, `CurrentUser` dep, `require_permission` factory) |
| `app/audit/` | Audit log: `log.py` (`log_event()` append-only insert into `audit_log` table, best-effort non-blocking; `@audited()` decorator for service methods), `middleware.py` (`ClientIPMiddleware` + `get_client_ip()` reads `X-Forwarded-For` for audit + rate limit) |
| `app/crypto/` | Symmetric encryption: `aes.py` (AES-256-GCM via `cryptography` lib, 12-byte nonce, nonce-prefixed output; `encrypt_str` / `decrypt_str` for at-rest secrets, key from `KG_ENCRYPTION_KEY`) |
| `app/services/` | Cross-cutting service helpers: `email.py` (magic-link email sender via SMTP, MailHog in dev) |
| `app/celery_app.py` | Celery 5.4 factory; broker = Redis DB 0, backend = DB 1; `task_acks_late=True`, `prefetch_multiplier=1` (one task per worker), `task_default_max_retries=3`; eager mode flag for tests |
| `app/sources/` | Source connector framework: `base.py` (`BaseSourceConnector` ABC + `SourceDoc` dataclass + `ConnectorAuthError` / `ConnectorRateLimitError`), `google_drive.py` (OAuth + Changes API + `changes.watch` push notifications), `notion.py` (integration token + page/block walk), `sync.py` (sync engine: load source → decrypt config → validate creds → list changes → fetch + upload to MinIO + upsert Document row + emit progress), `progress.py` (Redis pub/sub on `kg:sync:{job_id}:progress`, consumed by SSE endpoint) |
| `app/tasks/` | Celery task entrypoints: `sync.py` — `sync_source_task` (one source; retries 3x 30s, no retry on auth error) and `sync_all_sources_task` (enqueue every ACTIVE source); `beat_schedule.py` — `sync-all-sources-every-5-min` Beat entry driven by `SYNC_INTERVAL_MINUTES` |
| `app/api/v1/` | API routers: `auth.py` — 6 endpoints (`/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/oauth/{provider}` + `/callback`, `/auth/magic-link` + `/verify`); `sources.py` — admin CRUD + `POST /sources/{id}/sync` (manual trigger) + sync-job list/detail (`manage_sources` permission gate, returns only metadata — `config_encrypted` never exposed); `webhooks.py` — `POST /webhooks/google-drive` (verifies `X-Goog-Channel-Token`, returns 200 for initial `sync` ping, enqueues `sync_source_task` for `update`/`exists`); Pydantic request/response schemas; role-claim JWT; audit emit on register / login / logout |
| `alembic/` | Alembic migrations (env, script template, `versions/0001_initial_schema.py`) |
| `scripts/init.py` | Idempotent infra init: Qdrant collection + MinIO bucket + seed (run by Compose `init` container) |
| `scripts/seed.py` | Default data: 1 admin user, 3 roles, 2 access groups, `system_settings` singleton |
| `scripts/init_helpers.py` | Per-step init coroutines (Qdrant / MinIO / seed) |
| `tests/test_health.py` | Smoke tests: `/health`, `/metrics`, `/api/v1` |
| `tests/sources/` | Source-connector unit tests: `test_base.py` (ABC contract + error hierarchy), `test_google_drive.py` (token refresh + Changes pagination + 401/429/403 + tombstone), `test_notion.py` (`_TokenBucket` pacing + block-to-Markdown), `test_sync.py` (full lifecycle + partial-fail + oversized skip + auth-failed short-circuit), `test_progress.py` (publish/subscribe + bad-JSON resilience), `test_webhook.py` (sync ping + unknown channel + enqueue path) |
| `.env` | Local env (gitignored) |
| `.venv/` | Virtualenv (gitignored) |

**Data model:** 14 PostgreSQL tables registered with `Base.metadata`. Migrations are versioned under `backend/alembic/versions/`. All models use UUID primary keys (server-side `gen_random_uuid()`) and `created_at` / `updated_at` timestamp mixins.

**Currently validated:** pytest 94/94 pass (auth + rbac + source connectors — 6 test modules); ruff/mypy configured; imports work; CORS allows `localhost:3000` and `${KG_DOMAIN}:3000`.

**Test coverage threshold:** `--cov-fail-under=80` (set in pyproject, will gate as the test suite grows).

## 3. Frontend (`frontend/`)

Next.js 14.2 App Router, TypeScript 5.6 strict, Tailwind, shadcn/ui patterns, i18n via `next-intl`.

| File | Purpose |
|------|---------|
| `package.json` | Deps: next 14.2, react 18.3, zustand 4, tanstack-query 5, next-intl 3, zod 3, lucide-react |
| `tsconfig.json` | TypeScript strict mode |
| `next.config.mjs` | Next.js + i18n routing config |
| `tailwind.config.ts` | Tailwind config with shadcn-style theme tokens |
| `postcss.config.mjs` | PostCSS pipeline for Tailwind |
| `.eslintrc.json` | ESLint + `eslint-config-next` |
| `Dockerfile` | Multi-stage: deps → builder → runner (non-root UID 1001, standalone output, healthcheck) |
| `app/layout.tsx` | Root layout with `NextIntlClientProvider`, locale from server |
| `app/page.tsx` | Landing page with i18n keys (home.title, home.subtitle, etc.) |
| `app/globals.css` | Tailwind base + CSS vars |
| `i18n/config.ts` | `next-intl` config (locales, default) |
| `i18n/request.ts` | Locale request handler for server components |
| `messages/en.json` | English strings (home, common, auth, nav, query) |
| `messages/vi.json` | Vietnamese strings (full mirror of en.json) |
| `components/` | Empty stub (components added as the frontend grows) |
| `lib/` | Empty stub (lib code added as the frontend grows) |
| `public/` | Static assets |

**i18n scope:** VI + EN, default EN per D12. All user-facing strings localized (home, common, auth, nav, query sections).

## 4. CLI (`cli/`)

Placeholder for the CLI (Typer-based, to be added). Currently:

- `cli/knowgate_cli/` — package skeleton.
- `cli/tests/` — placeholder.

Not used yet. `make cli-install` target exists for future install in editable mode.

## 5. Deploy (`deploy/`)

| File | Purpose |
|------|---------|
| `docker-compose.yml` | 11-service stack: init (one-shot), api, worker, beat, frontend, postgres, redis, qdrant, minio, mailhog, litellm. All env-driven, fail-fast on missing required vars, healthchecks, named volumes, single `kg-net` bridge network. |
| `docker-compose.dev.yml` | Dev overlay: hot-reload (uvicorn `--reload`, `npm run dev`), source bind mounts, `KG_LOG_LEVEL=DEBUG`, builder target for frontend. |
| `litellm/config.yaml` | LiteLLM proxy config: `gpt-4o-mini` (default, OpenAI) + `ollama/llama3` (fallback), `enable_fallbacks: true`, `request_timeout: 30`, master key from env. |

**Compose file structure:**
- Atomic env vars: `${DB_USER:?DB_USER required}` syntax fails fast at startup.
- Healthchecks on every long-running service.
- The `init` one-shot container runs `alembic upgrade head` + `python -m scripts.init` (Qdrant collection + MinIO bucket + seed) and exits 0. The `api` service depends on `init: service_completed_successfully`, so it never serves traffic against an un-migrated schema.
- Dependents use `condition: service_healthy` (api waits for postgres, redis, qdrant, minio, litellm).
- Volumes: `postgres-data`, `redis-data`, `qdrant-data`, `minio-data`.

## 6. CI (`.github/workflows/ci.yml`)

5 jobs + 1 status gate:

1. **backend-lint** — ruff check + ruff format check (working dir: `backend/`).
2. **backend-test** — pytest `tests/test_health.py` with test env (test keypair + dummy DB vars).
3. **frontend-lint** — eslint + `tsc --noEmit` + prettier check (working dir: `frontend/`).
4. **frontend-build** — `next build` (needs lint).
5. **docker-validate** — `docker compose config --quiet` for base + dev overlay (with dummy `.env`).
6. **ci-status** — gate: fails if any of the above fails.

**Triggers:** push to `main`, PRs targeting `main`.
**Caching:** pip (pyproject.toml), npm (package-lock.json).

## 7. Env Config (`.env.example`)

121 lines, all atomic. Key blocks: `KG_*` (general + JWT + encryption), `DB_*` (Postgres), `REDIS_*`, `QDRANT_*` (host/port/grpc/api_key/collection), `MINIO_*` (endpoint/port/user/password/bucket), `LITELLM_*` (host/port/key/model), `OPENAI_API_KEY`, `EMBEDDING_*` (model/dim/device/batch/cache_ttl), OAuth (Google + GitHub), `SMTP_*`, rate limits, sync, query, feedback retention, bootstrap admin.

## 8. Make Targets

| Target | Effect |
|--------|--------|
| `help` | Print target catalog (default) |
| `up` | `docker compose up -d` (base + dev overlay), print health |
| `down` | Stop all services |
| `logs` | Tail logs (all services) |
| `ps` | List running services |
| `restart` | Restart all |
| `build` | Build images |
| `pull` | Pull base images |
| `migrate` | `alembic upgrade head` inside api container |
| `seed` | `python -m scripts.seed` inside api (admin user, 3 roles, 2 access groups, system_settings) |
| `init` | `python -m scripts.init` inside api (Qdrant collection + MinIO bucket + seed; idempotent) |
| `install` | Create backend `.venv` + pip install editable `[dev]` |
| `test` | `pytest` in backend venv |
| `lint` | ruff (BE) + npm run lint (FE) |
| `format` | ruff format (BE) + npm run format (FE) |
| `clean` | `docker compose down -v --remove-orphans` + system prune (DESTRUCTIVE) |
| `secrets` | Generate JWT RS256 key pair + 32-byte base64 encryption key (prints to .env instructions) |
| `cli-install` | `pip install -e .` in `cli/` (when CLI is added) |

## 9. Documentation Inventory

| Doc | Status | Audience |
|-----|--------|----------|
| `README.md` | Complete | New developers (quickstart) |
| `docs/project-overview-pdr.md` | Draft (this batch) | Stakeholders, contributors |
| `docs/system-architecture.md` | Draft (this batch) | Engineers, ops |
| `docs/code-standards.md` | Draft (this batch) | All contributors |
| `docs/deployment-guide.md` | Draft (this batch) | Devs, self-hosters |
| `docs/codebase-summary.md` | Draft (this file) | New contributors |

## 10. What's NOT shipped yet (planned for future)

- REST API: ~30 remaining routes (documents, RBAC users/groups, settings, sync-jobs SSE).
- Frontend pages: login, dashboard, query, admin, more i18n keys.
- CLI: Typer-based, query + admin ops.
- Observability: OpenTelemetry, Prometheus exporters, Grafana JSON, Loki.
- Helm chart: K8s production deploy.
- E2E: Playwright E2E, k6 load, integration suite.

## 11. Notes for Future Updates

- `repomix` is not currently installed in this environment. To regenerate this summary automatically: `npm i -g repomix && repomix --output repomix-output.xml`, then parse and update this file.
- When adding new modules, follow the established pattern: kebab-case file names, module < 200 lines, atomic env vars, no hardcoded values, full i18n keys for user-facing strings.
- Update the changelog frontmatter field when modifying any doc.
