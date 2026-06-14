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

| File | Purpose |
|------|---------|
| `pyproject.toml` | Single source of deps + tool config (ruff, mypy strict, pytest) |
| `Dockerfile` | Multi-stage: builder (hatch) → runtime (slim, non-root UID 1001, healthcheck) |
| `.dockerignore` | Excludes `.venv`, `.pytest_cache`, etc. from build context |
| `app/__init__.py` | Package marker |
| `app/main.py` | FastAPI app, lifespan, CORS, metrics middleware, `/health`, `/ready`, `/metrics`, `/api/v1` |
| `app/config.py` | Pydantic v2 `Settings`, atomic env vars, computed URLs, encryption key validator |
| `app/logging.py` | structlog JSON (prod) + console (dev), bridges stdlib logging |
| `tests/test_health.py` | 3 smoke tests: `/health`, `/metrics`, `/api/v1` |
| `.env` | Local env (gitignored) |
| `.venv/` | Virtualenv (gitignored) |

**Currently validated:** 3/3 pytest pass; ruff/mypy configured; imports work; CORS allows `localhost:3000` and `${KG_DOMAIN}:3000`.

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
| `docker-compose.yml` | 10-service stack: postgres, redis, qdrant, minio, mailhog, litellm, init, api, worker, beat, frontend. All env-driven, fail-fast on missing required vars, healthchecks, named volumes, single `kg-net` bridge network. |
| `docker-compose.dev.yml` | Dev overlay: hot-reload (uvicorn `--reload`, `npm run dev`), source bind mounts, `KG_LOG_LEVEL=DEBUG`, builder target for frontend. |
| `litellm/config.yaml` | LiteLLM proxy config: `gpt-4o-mini` (default, OpenAI) + `ollama/llama3` (fallback), `enable_fallbacks: true`, `request_timeout: 30`, master key from env. |

**Compose file structure:**
- Atomic env vars: `${DB_USER:?DB_USER required}` syntax fails fast at startup.
- Healthchecks on every long-running service.
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

121 lines, all atomic. Key blocks:

- **General:** `KG_ENV`, `KG_LOG_LEVEL`, `KG_DOMAIN`.
- **JWT (RS256):** key paths, algorithm, 15-min access, 30-day refresh.
- **Encryption:** `KG_ENCRYPTION_KEY` (required, 32-byte base64).
- **PostgreSQL:** `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.
- **Redis:** `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`.
- **Qdrant:** `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_GRPC_PORT`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`.
- **MinIO:** `MINIO_ENDPOINT`, `MINIO_PORT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_BUCKET`, `MINIO_PUBLIC_ENDPOINT`.
- **LLM (LiteLLM):** `LITELLM_HOST`, `LITELLM_PORT`, `LITELLM_MASTER_KEY`, `LITELLM_DEFAULT_MODEL`, `LITELLM_FALLBACK_MODEL`.
- **OpenAI + Ollama** provider keys.
- **Embedding:** `EMBEDDING_MODEL_NAME` (BAAI/bge-m3), `EMBEDDING_DIM` (1024), `EMBEDDING_DEVICE` (cpu/cuda), `EMBEDDING_BATCH_SIZE`, `EMBEDDING_CACHE_TTL`.
- **OAuth:** Google + GitHub client id/secret/redirect/scope (all optional in dev).
- **SMTP:** `SMTP_HOST` (mailhog in dev), port, user, password, from, TLS.
- **Rate limits, search, sync, query, feedback retention, bootstrap admin.**

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
| `migrate` | `alembic upgrade head` inside api container (when Data Layer is added) |
| `seed` | `python -m scripts.seed` inside api (when Auth is added) |
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

- Data Layer: PostgreSQL schemas, Alembic migrations, Qdrant collection init.
- Auth: endpoints, OAuth handlers, JWT middleware, RBAC filter, audit log.
- Source Connectors: Google Drive + Notion, sync job lifecycle.
- Ingestion Pipeline: Unstructured parser, chunker, bge-m3 embed, Qdrant upsert.
- Retrieval + LLM: Hybrid search, reranker, query rewrite, LLM call, answer with citation.
- REST API: ~40 routes (sources, sync-jobs, documents, RBAC, settings).
- Frontend pages: login, dashboard, query, admin, more i18n keys.
- CLI: Typer-based, query + admin ops.
- Observability: OpenTelemetry, Prometheus exporters, Grafana JSON, Loki.
- Helm chart: K8s production deploy.
- E2E: Playwright E2E, k6 load, integration suite.

## 11. Notes for Future Updates

- `repomix` is not currently installed in this environment. To regenerate this summary automatically: `npm i -g repomix && repomix --output repomix-output.xml`, then parse and update this file.
- When adding new modules, follow the established pattern: kebab-case file names, module < 200 lines, atomic env vars, no hardcoded values, full i18n keys for user-facing strings.
- Update the changelog frontmatter field when modifying any doc.
