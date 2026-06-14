---
type: project-changelog
status: active
created: 2026-06-14
updated: 2026-06-14
owner: "@seang"
tags: [changelog, know-gate, release-notes]
links:
  - "[[README.md]]"
  - "[[docs/system-architecture.md]]"
  - "[[docs/codebase-summary.md]]"
  - "[[docs/project-overview-pdr.md]]"
changelog:
  - 2026-06-14 | manual | rewrote source-connectors release entry with full module + env-var + schema detail; moved above auth entry
  - 2026-06-14 | manual | source connectors shipped: 2 connectors, sync engine, Celery, 8 admin endpoints, 40 tests; flag schema-drift
  - 2026-06-14 | manual | initial changelog with auth + rbac entry
---

# KnowGate — Project Changelog

> Detailed record of significant changes, features, and fixes shipped to the codebase.
> Public-facing release notes live here; internal task tracking stays local.
> Newest entries on top. Format: `<date> | <scope> | <summary>`.

## Unreleased

- _Nothing yet._

## 2026-06-14

### feat: source connectors (google drive + notion)

Adds the sync engine, two source adapters, Celery tasks, and the admin API surface for source management. Sync runs end-to-end: list changes → fetch → upload to MinIO → upsert Document row → emit progress. Polling fallback fires every 5 min; Drive push notifications are received via webhook.

**Source connectors (2):**

| Connector | Auth | Sync model | Rate limit | Notes |
|-----------|------|------------|------------|-------|
| Google Drive | OAuth (access + refresh token) | Changes API (`startPageToken` cursor) | 429 with `Retry-After` backoff; auto refresh within 5-min grace | Optional `folder_id` filter, tombstone on `removed` / `trashed` |
| Notion | Integration token (pinned `Notion-Version: 2022-06-28`) | Full-list per run; cursor = max `last_edited_time` | 3 req/s via in-process `_TokenBucket` | `/blocks/{id}/children` paginated, flattened to Markdown |

**Adapter pattern:** `BaseSourceConnector` ABC with 3 abstract methods (`validate_credentials`, `list_changes(cursor)`, `fetch_doc(doc_id)`). Each concrete connector ships a `serialize_config` / `deserialize_config` pair; the sync engine decrypts `Source.config_encrypted` (AES-256-GCM) once per run.

**Sync engine (`app/sources/sync.py`):**

- Lifecycle: load Source → decrypt config → build connector → validate creds → list changes → for each doc: size cap check (50 MB) → fetch → MinIO upload → upsert Document row → publish progress
- Status transitions: `QUEUED` → (running) → `COMPLETED` | `PARTIAL` | `FAILED`
- Per-doc error containment: 1 failed doc does not block the batch
- `auth_failed` short-circuits future syncs for that source
- Cursor persisted on Source row; `last_sync_at` / `last_error` updated each run

**Celery (`app/celery_app.py` + `app/tasks/sync.py` + `app/tasks/beat_schedule.py`):**

- `celery_app` factory: Redis broker + result backend, `task_acks_late=True`, `worker_prefetch_multiplier=1`, 3 retries with 30s default delay
- `sync_source_task(source_id, triggered_by)` — entry point, creates the `SyncJob` row
- `sync_all_sources_task()` — Beat-triggered every 5 min (configurable via `settings.sync_interval_minutes`)
- Auth errors are NOT retried (need admin intervention)

**Progress events (`app/sources/progress.py`):**

- `publish_event(job_id, stage, current, total, failed, message, doc_id)` to Redis pub/sub on `kg:sync:{job_id}:progress`
- `subscribe_events(job_id)` async generator for SSE (SSE route to be added in the REST API work block)
- Best-effort: Redis outage logs + continues

**API endpoints (mounted at `/api/v1`, admin-gated via `Permission.MANAGE_SOURCES`):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/sources` | List sources (metadata only — `config_encrypted` never returned) |
| POST | `/sources` | Create source; encrypts connector config via `KG_ENCRYPTION_KEY` |
| GET | `/sources/{id}` | Read one source |
| PATCH | `/sources/{id}` | Update name / status |
| DELETE | `/sources/{id}` | Soft delete (status → `archived`) |
| POST | `/sources/{id}/sync` | Manual trigger (202 Accepted) |
| GET | `/sources/sync-jobs` | List jobs (optional `source_id` filter) |
| GET | `/sources/sync-jobs/{id}` | Read one job |
| POST | `/api/v1/webhooks/google-drive` | Drive push notification handler |

**Source model — 4 new columns:**

- `sync_cursor` (TEXT) — Changes API startPageToken / max last_edited_time
- `webhook_channel_id` (String(128), indexed) — Drive `changes.watch` channel ID
- `webhook_resource_id` (String(128)) — Drive resource ID
- `webhook_expires_at` (DateTime) — Watch TTL (7 days for Drive)

**Known issue — schema drift:** The 4 new columns are on the SQLAlchemy model but the initial Alembic migration `0001_initial_schema.py` was not updated. Fresh `make up` will fail at `alembic upgrade head` against a clean DB. Migration `0002_add_source_webhook_fields.py` is required as a pre-task for the ingestion pipeline. Test suite passes because tests use `Base.metadata.create_all()` against a test DB, which honors the current model — only the migration is behind. **Tracked as an ingestion-pipeline blocker.**

**OAuth refresh note:** the Google Drive connector refreshes the access token in memory on 401 / near-expiry but does NOT re-encrypt + persist the refreshed config on the Source row. The refresh is lost on next connector instantiation. To be fixed alongside the first live Drive source test in the ingestion-pipeline work block.

**New modules:**

- `backend/app/sources/base.py` — ABC + `SourceDoc` + error hierarchy
- `backend/app/sources/google_drive.py` — Drive connector + OAuth config helpers
- `backend/app/sources/notion.py` — Notion connector + `_TokenBucket` + block-to-Markdown
- `backend/app/sources/sync.py` — sync engine
- `backend/app/sources/progress.py` — Redis pub/sub events
- `backend/app/tasks/sync.py` — Celery tasks
- `backend/app/tasks/beat_schedule.py` — Beat schedule
- `backend/app/api/v1/sources.py` — CRUD + manual sync
- `backend/app/api/v1/webhooks.py` — Drive push handler
- `backend/app/celery_app.py` — Celery factory
- `backend/tests/sources/*` — 6 test files (40 tests)

**New env vars:** none (all source-connector config is per-row in `Source.config_encrypted`).

**Tests:** 40 new source-connector unit tests; 94/94 total pass (`pytest backend/tests/`). `ruff check` clean on all touched files.

**Docs updated:**

- `docs/codebase-summary.md` — added `app/sources/`, `app/tasks/`, `app/celery_app.py` rows; removed Source Connectors from "NOT shipped yet"
- `docs/system-architecture.md` — updated write-path description to include sync engine + Beat, added Sources row to API surface
- `docs/project-overview-pdr.md` — marked Source Connectors capability as shipped
- `docs/project-changelog.md` — this entry

## 2026-06-14

### feat: source connectors

Adds ingestion from Google Drive and Notion: connector framework, sync engine, Celery task + Beat schedule, source management API, and Drive push-notification webhook.

**Connector framework (`backend/app/sources/`):**

- `BaseSourceConnector` ABC with 3 abstract methods: `validate_credentials()`, `list_changes(cursor) -> (docs, next_cursor)`, `fetch_doc(doc_id) -> (bytes, metadata)`. Shared `SourceDoc` dataclass carries provider-stable `id`, `title`, `mime_type`, `modified_at`, `url`, `size_bytes`, `extra`, `is_deleted`. Typed errors: `ConnectorAuthError` (token expired / revoked / insufficient scope — sync engine marks source `auth_failed`), `ConnectorRateLimitError` (429 — `retry_after` seconds).
- `GoogleDriveConnector`: OAuth via Authlib, `list_changes` uses Drive Changes API with `startPageToken` cursor, `fetch_doc` downloads via httpx + uploads to MinIO, `validate_credentials` triggers token refresh on 401, registers `changes.watch` for push notifications.
- `NotionConnector`: integration token (user-pasted), `list_changes` uses search API, `fetch_doc` walks page + child blocks recursively and exports Markdown, rate-limited to 3 req/s.
- `Connector factory` (`sync.py:build_connector`): instantiates the right connector from a `Source` row, decrypts `config_encrypted` once with `KG_ENCRYPTION_KEY`.

**Sync engine (`app/sources/sync.py`):**

`run_sync(source_id, job_id, triggered_by)` — single source, idempotent, resumable per batch.

1. Load `Source` row from DB.
2. Decrypt `config_encrypted` (AES-256-GCM) and build the connector.
3. `validate_credentials` — mark source `auth_failed` on `ConnectorAuthError`, finalize job `failed`.
4. `list_changes(cursor)` — discover new / updated / deleted docs; persist `next_cursor` on `Source` at the end. Tombstones (`is_deleted=True`) mark `Document.status=deleted`.
5. For each doc: skip if `size_bytes > MAX_DOC_SIZE_MB` (default 50 MB, logged as `sync_doc_too_large`); else `fetch_doc` → upload raw bytes to MinIO under `{type}/{source_id}/{doc_id}` → upsert `Document` row by `(source, source_id)` natural key (Postgres `ON CONFLICT DO UPDATE` with `source_modified_at` guard) → publish progress event to Redis.
6. Mark job `completed` (no failed docs) / `partial` (some failed) / `failed` (all failed). Best-effort close of the connector.

**Progress events (`app/sources/progress.py`):**

- Channel: `kg:sync:{job_id}:progress` (Redis pub/sub).
- Event schema: `{ts, stage, current, total, failed, message, doc_id?}` where `stage ∈ {start, fetch, delete, skip, failed, complete}`.
- `publish_event` is best-effort — Redis outage logs and continues.
- `subscribe_events` is the async iterator the SSE endpoint wraps in `data: <json>\n\n` frames.

**Celery wiring:**

- `app/celery_app.py`: Celery 5.4 factory. Broker = Redis DB 0, backend = DB 1 (derived from `REDIS_HOST` / `REDIS_PORT` via `celery_broker_url` / `celery_result_backend`). `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1` (one heavy sync per worker), `task_default_max_retries=3`, `task_default_retry_delay=30s`, JSON serializer, `result_expires=3600s`. `task_always_eager=settings.celery_task_always_eager` for tests.
- `app/tasks/sync.py`:
  - `sync_source_task(source_id, triggered_by)` — creates a `QUEUED` `SyncJob` row, calls `asyncio.run(run_sync(...))`, retries 3× with 30s delay on transient failures, does NOT retry auth errors. Returns the job ID.
  - `sync_all_sources_task` — queries `Source` rows where `status='active'`, enqueues one `sync_source_task(triggered_by="scheduled")` per source.
- `app/tasks/beat_schedule.py`: `beat_schedule["sync-all-sources-every-5-min"]` runs `sync_all_sources` at `float(SYNC_INTERVAL_MINUTES * 60)` seconds (default 300s).

**Source management API (`backend/app/api/v1/sources.py`):**

All endpoints require `Permission.MANAGE_SOURCES` (admin role). `config_encrypted` is **never** returned in responses (only `type`, `name`, `status`, `last_sync_at`, `last_error`).

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/sources` | list (newest first) |
| POST   | `/sources` | create — encrypts `config` dict with `KG_ENCRYPTION_KEY`, stores as `config_encrypted` |
| GET    | `/sources/{id}` | read |
| PATCH  | `/sources/{id}` | update `name` / `status` |
| DELETE | `/sources/{id}` | archive (soft delete — sets `status=archived`, keeps history) |
| POST   | `/sources/{id}/sync` | manual trigger — enqueues `sync_source_task(triggered_by="manual")` via `.delay()`; returns 202 with placeholder job (client polls `/sources/sync-jobs`) |
| GET    | `/sources/sync-jobs` | list jobs, optional `?source_id=` filter, `?limit=` (default 50), most-recent first |
| GET    | `/sources/sync-jobs/{id}` | read job |

**Drive webhook (`backend/app/api/v1/webhooks.py`):**

`POST /api/v1/webhooks/google-drive` — no auth (provider-facing).

- Verifies `X-Goog-Channel-Token` is present (returns 400 otherwise).
- `X-Goog-Resource-State=sync` (initial channel-creation ping) → 200, no-op.
- Looks up `Source` by `webhook_channel_id`. Unknown channel → 200 `{"received":"unknown"}` (log warning, don't spam retries on misconfig).
- Otherwise enqueues `sync_source_task(triggered_by="webhook")` and returns 202 `{"received":"enqueued","source_id":...}`.

**Source model extensions (`backend/app/db/models/source.py`):**

New columns on `sources`:
- `sync_cursor` (TEXT, nullable) — opaque provider cursor (Drive `startPageToken`, Notion `updated_at`).
- `webhook_channel_id` (STRING(128), nullable, indexed) — Drive `changes.watch` channel ID; used by webhook handler to route the push.
- `webhook_resource_id` (STRING(128), nullable) — Drive resource ID returned by `changes.watch`.
- `webhook_expires_at` (DATETIME, nullable) — channel TTL (7 days for Drive); connector re-registers before expiry.

`sync_jobs` table is unchanged at the schema level; lifecycle values used by the engine are `queued` / `running` / `completed` / `partial` / `failed`, with `triggered_by ∈ {manual, scheduled, webhook}`.

**New env vars (all atomic, no fallbacks):** `SYNC_INTERVAL_MINUTES` (default 5), `SYNC_MAX_CONCURRENT` (default 3), `SYNC_BATCH_SIZE` (default 100), `MAX_DOC_SIZE_MB` (default 50), `CELERY_BROKER_URL` (optional, derives from `REDIS_URL`), `CELERY_RESULT_BACKEND` (optional, derives from `REDIS_URL`), `CELERY_TASK_ALWAYS_EAGER` (test flag).

**Tests:** connector unit tests with mocked provider APIs, end-to-end sync of fixture docs, edge cases for rate limit / token expiry / partial fail / concurrent jobs, webhook handler tests for `sync` vs `update` vs unknown channel.

**Docs updated:**

- `docs/codebase-summary.md` — added `app/celery_app.py`, `app/sources/`, `app/tasks/`, `app/api/v1/sources.py` + `webhooks.py` rows; removed Source Connectors from "NOT shipped yet"
- `docs/system-architecture.md` — added `Write path (sync)` paragraph covering Beat → worker → connector → MinIO → Document upsert → progress; added Source / Sync jobs / Webhook rows to API surface table
- `docs/project-overview-pdr.md` — marked Source Connectors, Sync job lifecycle, and Document status as shipped in the Ingest section
- `docs/project-changelog.md` — this entry

### feat: auth + rbac

Adds the complete authentication and role-based access control layer.

**Auth endpoints (6 routes, mounted at `/api/v1/auth`):**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/register` | Bootstrap first user as admin (closed once any user exists) |
| POST | `/login` | Email + password → JWT pair; rate-limited 5/15min per ip+email-hash |
| POST | `/oauth/{provider}` | Generate authorize URL (Google or GitHub, PKCE) |
| GET | `/oauth/{provider}/callback` | Provider redirect target; state CSRF check; upserts user; issues JWT pair |
| POST | `/magic-link` | Email sign-in link; 202 always (no account-existence leak) |
| GET | `/magic-link/verify` | Consume one-shot token; returns JWT pair |
| POST | `/refresh` | Rotate refresh token; revoke old jti in Redis |
| POST | `/logout` | Revoke current access jti in Redis until original exp |

**Token model:** RS256 JWT, 15-min access + 30-day refresh, `jti` claim for revocation in Redis, `roles` claim for downstream permission checks, `typ` claim (`access` | `refresh`) blocks cross-type confusion.

**Password model:** argon2id with OWASP 2024 parameters (`time_cost=3`, `memory_cost=64 MiB`, `parallelism=4`); transparent rehash on successful login if parameters drift.

**OAuth model:** Authlib `AsyncOAuth2Client`, Authorization Code + PKCE, state in Redis with 5-min TTL and atomic get+delete on callback (CSRF defense). Google + GitHub providers wired; first user from any provider is admin, subsequent are member.

**Magic-link model:** 32-byte URL-safe token, SHA-256-hashed at rest, 15-min TTL, single-use via atomic Redis `GET+DEL` pipeline.

**RBAC (3 flat roles per OQ-7):**

| Role | Permissions |
|------|-------------|
| admin | all 9 |
| editor | `view_doc`, `edit_doc_metadata` |
| member | `view_doc` |

Permissions: `view_doc`, `edit_doc_metadata`, `delete_doc`, `manage_users`, `manage_roles`, `manage_groups`, `manage_sources`, `manage_settings`, `invite_user`, `view_audit_log`.

**Permission enforcement:** `CurrentUser` FastAPI dep extracts user from `Authorization: Bearer <jwt>`; `require_permission(Permission.X)` factory raises 403 if any of the user's roles lacks the permission.

**Audit log:** append-only inserts into `audit_log` table; best-effort, non-blocking (`asyncio.create_task`); log writes never raise to keep request flow alive. `audited()` decorator available for service-method emitters.

**ClientIP middleware:** ASGI middleware reads `X-Forwarded-For` first-hop (or falls back to `client.host`); injects `request.state.client_ip` for audit + rate limit. Registered after CORS so proxy headers are parsed correctly.

**Encryption:** AES-256-GCM (12-byte nonce) for OAuth tokens at rest; key from `KG_ENCRYPTION_KEY` (32-byte base64).

**New modules:**

- `backend/app/auth/` — `jwt.py`, `password.py`, `oauth.py`, `magic_link.py`, `permissions.py`
- `backend/app/audit/` — `log.py`, `middleware.py`
- `backend/app/crypto/` — `aes.py`
- `backend/app/services/email.py` — magic-link SMTP sender (MailHog in dev)
- `backend/app/api/v1/auth.py` — 6-endpoint router

**New env vars (all atomic, no fallbacks):** `KG_DOMAIN`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `GITHUB_OAUTH_REDIRECT_URI`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `KG_ENCRYPTION_KEY`, `RATE_LIMIT_LOGIN_PER_15MIN`, `JWT_PRIVATE_KEY_PATH`, `JWT_PUBLIC_KEY_PATH`, `JWT_ACCESS_TTL_SECONDS`, `JWT_REFRESH_TTL_SECONDS`, `MAGIC_LINK_TTL_MINUTES`, `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`.

**New tables:** none (uses existing `users`, `roles`, `user_roles`, `audit_log` tables).

**Tests:** register / login / refresh / logout / oauth flow / magic-link flow / RBAC enforcement / audit log emission all pass via `pytest`.

**Docs updated:**

- `docs/codebase-summary.md` — added `app/auth/`, `app/audit/`, `app/crypto/`, `app/services/`, `app/api/v1/` rows; removed Auth from "NOT shipped yet"
- `docs/system-architecture.md` — added Auth path paragraph to Section 4; updated API service row
- `docs/project-overview-pdr.md` — marked Auth + RBAC capability as shipped with full sub-bullets
- `docs/project-changelog.md` — this entry

## See also

- [[README.md]] — quickstart
- [[docs/system-architecture.md]] — service topology + auth path
- [[docs/codebase-summary.md]] — module inventory
- [[docs/project-overview-pdr.md]] — capability status
