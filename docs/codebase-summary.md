---
type: codebase-summary
status: draft
created: 2026-06-14
updated: 2026-06-15
owner: "@seang"
tags: [codebase-summary, know-gate, monorepo]
links:
  - "[[README.md]]"
  - "[[docs/system-architecture.md]]"
  - "[[docs/project-overview-pdr.md]]"
  - "[[docs/api/error-codes.md]]"
changelog:
  - 2026-06-15 | manual | CLI shipped: Typer + httpx + rich + keyring; 9 modules, 78 tests, exit code mapping (0-5), 6 sub-commands (auth/query/source/user/config), keyring sidecar for multi-account, refresh-on-401 with bounded retry, JSON mode via --json; CI jobs added (cli-lint + cli-test)
  - 2026-06-15 | manual | frontend shipped: 53 files (lib, components, app), i18n en/vi, middleware auth gate, server actions, 15 routes, 87-122 kB First Load JS
  - 2026-06-14 | /cook | REST API shipped: 60 routes under /api/v1 (RBAC, settings, audit-log, sync-job retry + SSE stream, cursor pagination); app/api/{responses.py, errors.py, middleware.py (RateLimitMiddleware), pagination.py}; standard error envelope (E1-E15)
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
| `app/api/v1/` | API routers (11 files, 60 routes total under `/api/v1`): `auth.py` (7), `query.py` (3), `feedback.py` (1), `sources.py` (7), `sync_jobs.py` (4 — list / detail / retry / SSE), `documents.py` (5), `users.py` (7), `roles.py` (4), `groups.py` (7), `settings.py` (3), `webhooks.py` (1). `sources.py` and `sync_jobs.py` admin-gated via `manage_sources` permission (returns only metadata — `config_encrypted` never exposed). Pydantic `response_model=` everywhere; standard error envelope E1-E15; cursor pagination; audit emit on register / login / logout |
| `app/api/` | Shared API utilities: `responses.py` (`ErrorCode` E1-E15 + `ErrorResponse` / `Page[T]` Pydantic models), `errors.py` (`to_error_response` + `api_error` helper, mounted as FastAPI exception handlers), `middleware.py` (`RateLimitMiddleware`, Redis sliding window 600 req/min/IP), `pagination.py` (cursor encode/decode + `PageParams`) |
| `tests/api/` | API tests (7 files: responses, users, roles, groups, documents, settings, sync_jobs) |
| `alembic/` | Alembic migrations (env, script template, `versions/0001_initial_schema.py`) |
| `scripts/init.py` | Idempotent infra init: Qdrant collection + MinIO bucket + seed (run by Compose `init` container) |
| `scripts/seed.py` | Default data: 1 admin user, 3 roles, 2 access groups, `system_settings` singleton |
| `scripts/init_helpers.py` | Per-step init coroutines (Qdrant / MinIO / seed) |
| `tests/test_health.py` | Smoke tests: `/health`, `/metrics`, `/api/v1` |
| `tests/sources/` | Source-connector unit tests: `test_base.py` (ABC contract + error hierarchy), `test_google_drive.py` (token refresh + Changes pagination + 401/429/403 + tombstone), `test_notion.py` (`_TokenBucket` pacing + block-to-Markdown), `test_sync.py` (full lifecycle + partial-fail + oversized skip + auth-failed short-circuit), `test_progress.py` (publish/subscribe + bad-JSON resilience), `test_webhook.py` (sync ping + unknown channel + enqueue path) |
| `.env` | Local env (gitignored) |
| `.venv/` | Virtualenv (gitignored) |

**Data model:** 14 PostgreSQL tables registered with `Base.metadata`. Migrations are versioned under `backend/alembic/versions/`. All models use UUID primary keys (server-side `gen_random_uuid()`) and `created_at` / `updated_at` timestamp mixins.

**Currently validated:** pytest 292/292 pass (auth + rbac + source connectors + pipeline + retrieval/LLM + REST API — 7 api test modules + 9 retrieval + 7 pipeline + 6 source); ruff/mypy configured; imports work; CORS allows `localhost:3000` and `${KG_DOMAIN}:3000`.

**Test coverage threshold:** `--cov-fail-under=80` (set in pyproject, will gate as the test suite grows).

## 3. Frontend (`frontend/`)

Next.js 14.2 App Router, TypeScript 5.6 strict, Tailwind, shadcn/ui patterns, i18n via `next-intl`. 53 source files total.

| File | Purpose |
|------|---------|
| `package.json` | Deps: next 14.2, react 18.3, zustand 4, tanstack-query 5, next-intl 3, zod 3, lucide-react |
| `tsconfig.json` | TypeScript strict mode |
| `next.config.mjs` | Next.js + i18n routing config |
| `tailwind.config.ts` | Tailwind config with shadcn-style theme tokens |
| `postcss.config.mjs` | PostCSS pipeline for Tailwind |
| `.eslintrc.json` | ESLint + `eslint-config-next` |
| `Dockerfile` | Multi-stage: deps → builder → runner (non-root UID 1001, standalone output, healthcheck) |
| `middleware.ts` | Next middleware: auth gate (redirects unauth users to `/{locale}/login`, preserves callback URL) + i18n locale prefix enforcement |
| `app/layout.tsx` | Root layout with `NextIntlClientProvider`, locale from server |
| `app/page.tsx` | Root redirect: signed-in users → `/dashboard`, others → `/{locale}/login` |
| `app/globals.css` | Tailwind base + CSS vars |
| `app/(auth)/layout.tsx` | Auth-shell layout (centered card, no app chrome) |
| `app/(auth)/login/page.tsx` | Email/password + OAuth (Google/GitHub) + magic-link send, with locale-aware redirect |
| `app/(auth)/login/login-form.tsx` | Client form: validation, error toast, pending state |
| `app/(auth)/magic-link/verify/page.tsx` | Magic-link token consume (server action), issues JWT pair, redirects to dashboard |
| `app/(auth)/magic-link/verify/magic-verify.tsx` | Client wrapper for the verify flow with status states |
| `app/(app)/layout.tsx` | Auth-gated app shell: sidebar (AppShell) + topbar (LangSwitcher + user menu), requires `UserProvider` |
| `app/(app)/dashboard/page.tsx` | Dashboard widgets: recent queries, active sources, quick actions |
| `app/(app)/dashboard/dashboard-widgets.tsx` | Widget composition (server + client split) |
| `app/(app)/query/page.tsx` | Query workspace: input → answer + citations + feedback buttons + filter sidebar |
| `app/(app)/query/query-workspace.tsx` | TanStack-Query-driven search/answer flow with streaming-friendly state |
| `app/(app)/query/history/page.tsx` | Caller's past queries (paginated, newest first) |
| `app/(app)/query/history/history-list.tsx` | History list with expand-to-citations |
| `app/(app)/admin/sources/page.tsx` | Sources list + create/edit dialog (admin only) |
| `app/(app)/admin/sources/sources-table.tsx` | Sources table with sync-trigger action |
| `app/(app)/admin/users/page.tsx` | Users list + invite + role-assign (admin only) |
| `app/(app)/admin/users/users-table.tsx` | Users table with role pills and last-admin guard |
| `app/(app)/admin/roles/page.tsx` | Roles list + CRUD (admin only; static-role + in-use blocks) |
| `app/(app)/admin/roles/roles-table.tsx` | Roles table with permission preview |
| `app/(app)/admin/groups/page.tsx` | Access groups list + user/document membership (admin only) |
| `app/(app)/admin/groups/groups-table.tsx` | Groups table with member counts |
| `app/(app)/admin/settings/page.tsx` | Singleton system settings editor (admin only) |
| `app/(app)/admin/settings/settings-view.tsx` | Settings form with audit-log link |
| `app/(app)/admin/audit-log/page.tsx` | Paginated audit log with `?user_id=` / `?action=` filters (admin only) |
| `app/(app)/admin/audit-log/audit-list.tsx` | Audit log list component |
| `components/ui/button.tsx` | shadcn/ui Button (variants: default / outline / ghost / destructive) |
| `components/ui/input.tsx` | shadcn/ui Input |
| `components/ui/label.tsx` | shadcn/ui Label |
| `components/ui/card.tsx` | shadcn/ui Card (Header / Title / Description / Content / Footer) |
| `components/ui/badge.tsx` | shadcn/ui Badge (variants for role/status) |
| `components/ui/skeleton.tsx` | shadcn/ui Skeleton (loading placeholders) |
| `components/ui/separator.tsx` | shadcn/ui Separator |
| `components/ui/alert.tsx` | shadcn/ui Alert (default / destructive variants) |
| `components/ui/dialog.tsx` | shadcn/ui Dialog (modal shell, used by admin CRUD forms) |
| `components/citation-card.tsx` | Per-citation card: title, section, page, source link, snippet |
| `components/feedback-buttons.tsx` | Good / bad / source-missing feedback for a query |
| `components/filter-sidebar.tsx` | Source / language / date filters for query page |
| `components/lang-switcher.tsx` | Locale switch (preserves current path) |
| `components/empty-state.tsx` | Reusable empty state with icon + title + description |
| `components/app-shell.tsx` | Sidebar nav (per role) + topbar (lang switcher + user menu) |
| `components/user-provider.tsx` | Server-side user context (decoded JWT + permissions) for client trees |
| `components/role-gate.tsx` | Client-side permission guard (renders children only if user has required permission) |
| `lib/api.ts` | Public barrel: re-exports `api-client.ts` + `api-types.ts` |
| `lib/api-client.ts` | Typed fetch wrapper: base URL, JWT injection, error envelope (E1-E15) handling, zod-validated responses, TanStack-Query helpers |
| `lib/api-types.ts` | Shared TypeScript types for API requests/responses (users, sources, queries, settings, etc.) |
| `lib/auth.ts` | Server-side auth helpers: get current user from cookies, permission check |
| `lib/auth-actions.ts` | Server actions: login, logout, refresh, magic-link verify |
| `lib/auth-cookies.ts` | HttpOnly cookie helpers (access + refresh JWT, secure flags, SameSite=Lax) |
| `lib/utils.ts` | `cn()` className merger (clsx + tailwind-merge) + misc formatters |
| `i18n/config.ts` | `next-intl` config (locales, default) |
| `i18n/request.ts` | Locale request handler for server components |
| `messages/en.json` | English strings — top-level keys: `home, common, auth, nav, query, dashboard, admin.{sources,users,roles,groups,settings,audit}, errors, toast, empty` |
| `messages/vi.json` | Vietnamese strings — full mirror of en.json (same key shape) |
| `public/` | Static assets |

**i18n scope:** VI + EN, default EN per D12. All user-facing strings localized across `home` (5), `common` (43), `auth` (19), `nav` (14), `query` (33), `dashboard` (10), `admin` (7 groups: sources, users, roles, groups, settings, settings, audit), `errors` (17), `toast` (8), `empty` (2). `en.json` and `vi.json` share identical key structure.

**Auth model:** HttpOnly secure cookies (access 15 min + refresh 30 days), same `RS256` JWT shape as the backend. `middleware.ts` runs on every non-static request, verifies access-token expiry (without DB hit), and rewrites the URL to `/{locale}/login?callbackUrl=...` on miss. Refresh handled by server actions on the server tree.

**Build output:** 15 routes, First Load JS 87-122 kB per route, ESLint + `tsc --noEmit` clean, `next build` green.

## 4. CLI (`cli/`)

Python 3.12, Typer 0.12, distributed as an installable package via `pip install -e .` in `cli/`. Entry point: `kg = "knowgate_cli.main:app"`.

| File / dir | Purpose |
|------------|---------|
| `pyproject.toml` | Deps: typer, httpx, pydantic, rich, keyring, tomli-w, respx (dev). Hatchling build, `kg` console script. |
| `Dockerfile` | (not yet — defer to follow-up) |
| `knowgate_cli/__init__.py` | `__version__ = "0.1.0"` |
| `knowgate_cli/main.py` | Typer app, sub-commands, global options (`--api-url`, `--json`, `--verbose`); per-subcommand `try/except CLIError → typer.Exit(code=...)` mapping |
| `knowgate_cli/client.py` | Sync `httpx.Client` wrapper; refresh-on-401 (one retry); error envelope `{"error": {"code", "message"}}` → `CLIError(exit_code=...)` per E1-E15 |
| `knowgate_cli/config.py` | TOML config at `~/.config/knowgate/config.toml`; keys `api_url`/`default_language`/`output_format`; atomic write via temp-file + rename |
| `knowgate_cli/output.py` | Rich + JSON mode; auto-detects TTY for `color`/`is_interactive`; `Output(json_mode=True)` short-circuits human output to a single JSON envelope |
| `knowgate_cli/auth.py` | `kg auth login/logout/status`; system keyring for tokens (`SERVICE_NAME="knowgate-cli"`, account key = `<api-url-hash>:<email>`); sidecar `credential_index.json` for `--all` logout without OS-level keyring enumeration |
| `knowgate_cli/query.py` | `kg query "..."`; supports positional / `--file` / `--stdin`; default human output is a Rich panel + citation table; `--json` echoes raw body |
| `knowgate_cli/source.py` | `kg source list/show/create/sync/delete`; interactive `create` (OAuth JSON for Drive, integration token for Notion) or file-driven `--from-file` |
| `knowgate_cli/user.py` | `kg user list/show/invite/delete` + nested `kg user role add/remove`; invite returns the one-time plaintext password in human mode (with share-securely warning) and as JSON in `--json` mode |
| `tests/conftest.py` | `isolated_config_dir` (per-test tmp `KNOWGATE_CONFIG_DIR`), `client` (no-creds), `mock_http` (respx transport) |
| `tests/test_config.py` (8) | defaults, persistence, atomic write, malformed TOML |
| `tests/test_client.py` (18) | exit-code mapping, envelope → `CLIError`, 204/2xx, auth-header injection, refresh-on-401, refresh-failure-stops-retry |
| `tests/test_auth.py` (10) | JSON round-trip, corrupt-entry cleanup, login flow, logout single + all, status while logged-in/out |
| `tests/test_query.py` (11) | question input resolution, POST payload, error propagation, no-result handling |
| `tests/test_source.py` (10) | list / show / sync / delete (with/without `--yes`), create from file (Drive + Notion), source-type validation |
| `tests/test_user.py` (8) | list (with filters), show, invite payload, role add (incl. noop), role remove |
| `tests/test_main.py` (13) | end-to-end via `CliRunner`: help, version, config get/set, query 0/2/4/1 exit codes, source list, user list |

**Sub-commands at a glance:** `kg auth {login,logout,status}` · `kg query [QUESTION]` · `kg config {list,get,set}` · `kg source {list,show,create,sync,delete}` · `kg user {list,show,invite,delete}` · `kg user role {add,remove}`.

**Exit codes (stable):** 0 success · 1 auth (401) · 2 not-found / usage (404 + bad arg) · 3 forbidden (403) · 4 rate-limited (429) · 5 generic (network, server error, unhandled).

**Auth model:** JWT pair in system keyring under `knowgate-cli` service. Multi-account via API-URL-hashed account key + sidecar `credential_index.json` (keyring has no portable "list all" API). Refresh handled by client on 401 (one retry).

**Test coverage:** 78/78 pass in ~0.5s; `ruff check` + `ruff format --check` clean. CI: `cli-lint` + `cli-test` jobs added to `.github/workflows/ci.yml`.

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
| `docs/project-overview-pdr.md` | Active | Stakeholders, contributors |
| `docs/system-architecture.md` | Active | Engineers, ops |
| `docs/code-standards.md` | Active | All contributors |
| `docs/deployment-guide.md` | Active | Devs, self-hosters |
| `docs/codebase-summary.md` | Active (this file) | New contributors |
| `docs/api/error-codes.md` | Active | API consumers (E1-E15 catalog) |

## 10. What's NOT shipped yet (planned for future)

- Observability: OpenTelemetry, Prometheus exporters, Grafana JSON, Loki.
- Helm chart: K8s production deploy.
- E2E: Playwright E2E, k6 load, integration suite.

## 11. REST API surface

| Group | Module | Routes | Auth |
|-------|--------|--------|------|
| Auth | `app/api/v1/auth.py` | register, login, refresh, logout, oauth/{google,github} (start + callback), magic-link (send + verify) | public / user |
| Query | `app/api/v1/query.py`, `app/api/v1/feedback.py` | POST /query, GET /query/history, GET /query/{id}, POST /feedback | user |
| Documents | `app/api/v1/documents.py` | list (cursor), detail, patch, delete, preview | user / editor / admin |
| Sources | `app/api/v1/sources.py` | list, detail, create, patch, delete, POST /{id}/sync | admin |
| Sync jobs | `app/api/v1/sync_jobs.py` | list, detail, POST /{id}/retry, GET /{id}/stream (SSE) | admin |
| RBAC | `app/api/v1/{users,roles,groups}.py` | full CRUD + assign (users↔roles, groups↔users, groups↔documents) | admin |
| Settings | `app/api/v1/settings.py` | GET/PATCH /settings, GET /settings/audit-log (cursor) | admin |
| Webhooks | `app/api/v1/webhooks.py` | POST /webhooks/google-drive | provider |
| Infra | `app/main.py` | /health, /ready (4-backend parallel), /metrics, /api/v1/openapi.json | public |

**Cross-cutting (`app/api/`):**
- `responses.py` — `ErrorCode` enum (E1-E15), `ErrorResponse` / `Page[T]` Pydantic models (catalog in [[docs/api/error-codes.md]])
- `errors.py` — `to_error_response(exc)` (pure mapping) + `api_error(...)` helper; mounted as FastAPI exception handlers in `app/main.py`
- `middleware.py` — `RateLimitMiddleware` (Redis sliding window, 600 req/min/IP, bypasses health/metrics/webhooks); adds `Retry-After` + `X-RateLimit-*` headers; emits E7 on throttle
- `pagination.py` — cursor encode/decode (base64 of `(created_at, id)` or `(name, id)`), `PageParams` (limit 20 default, max 100), `next_cursor_from_rows` helper

**Test coverage:** 292/292 pass (api: documents / groups / roles / settings / sync-jobs / users / response shape).

## 12. Notes for Future Updates

- `repomix` is not currently installed in this environment. To regenerate this summary automatically: `npm i -g repomix && repomix --output repomix-output.xml`, then parse and update this file.
- When adding new modules, follow the established pattern: kebab-case file names, module < 200 lines, atomic env vars, no hardcoded values, full i18n keys for user-facing strings.
- Update the changelog frontmatter field when modifying any doc.
