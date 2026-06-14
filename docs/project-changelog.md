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
  - "[[docs/api/error-codes.md]]"
changelog:
  - 2026-06-14 | /cook | 27 new REST endpoints, 60 total routes, 292/292 tests pass
  - 2026-06-14 | manual | retrieval + LLM shipped: query embedder + hybrid search (vector + PG FTS + RRF) + bge-reranker + LLM client (with circuit breaker) + answer generator + citation builder + semantic cache + no-result handler + query pipeline orchestrator; FTS migration; 4 new API endpoints (POST /query, history, get, POST /feedback); 61 new tests, 227/227 pass
  - 2026-06-14 | manual | ingestion pipeline shipped: parser + lang_detect + chunker + bge-m3 embedder + Qdrant bulk upsert + Celery ingest tasks + sync-to-ingest wiring; 72 new tests, 166/166 pass
  - 2026-06-14 | manual | rewrote source-connectors release entry with full module + env-var + schema detail; moved above auth entry
  - 2026-06-14 | manual | source connectors shipped: 2 connectors, sync engine, Celery, 8 admin endpoints, 40 tests; flag schema-drift
  - 2026-06-14 | manual | initial changelog with auth + rbac entry
---

# KnowGate — Project Changelog

> Detailed record of significant changes, features, and fixes shipped to the codebase.
> Public-facing release notes live here; internal task tracking stays local.
> Newest entries on top. Format: `<date> | <scope> | <summary>`.

## Unreleased

### feat: REST API endpoints (60 routes total)

Wires the full REST surface that the architecture calls for: standard `{data, meta}` / `{error: {code, message}}` envelope, cursor pagination, data-level permission filters, rate-limit middleware, and OpenAPI tags + BearerAuth security scheme. The 27 new routes (documents, users, roles, groups, settings, sync-jobs) plus the existing 33 (auth, sources, query, feedback, webhooks) bring the total to 60 mounted under `/api/v1`.

**Shared utilities (`backend/app/api/`):**

- `responses.py` — `ErrorCode` enum (E1-E15), `Page[T]`, `Meta`, `ErrorResponse` Pydantic models, `ok(data, meta=None)` + `error(code, message, ...)` helpers
- `pagination.py` — `PageParams` (default 20, max 100), `encode_cursor` / `decode_cursor` (forward-only, stable), `encode_role_cursor` / `decode_role_cursor` for permission-aware lists
- `errors.py` — `APIError`, `api_error(code, message, details=None)`, `to_error_response(exc)` maps `HTTPException` / `RequestValidationError` / `APIError` / generic `Exception` to HTTP status + `ErrorCode`
- `middleware.py` — `RateLimitMiddleware` (600 req/min/IP sliding window via Redis, `X-RateLimit-Limit` / `-Remaining` / `-Reset` response headers, `Retry-After` on 429, bypass for `/health`, `/metrics`, `/api/v1/webhooks/*`)
- `v1/_permissions.py` — data-level permission helpers (`filter_documents_for_user`, `filter_groups_for_user`, `assert_can_read_user`, `assert_can_modify_role`)

**Resource routers (`backend/app/api/v1/`):**

| Router | Routes | Highlights |
|--------|--------|------------|
| `documents.py` | 5 | list (permission-filtered, cursor pagination, source/status/language/date filters), get, patch (editor+), soft delete (admin), preview (presigned MinIO URL, 5-min TTL) |
| `users.py` | 7 | list / invite (one-time password via magic-link sender) / get / patch / soft delete (GDPR) / assign-role / revoke-role. **Last-admin guard:** cannot remove the only admin's `admin` role or delete the only admin |
| `roles.py` | 4 | list / create / patch / delete. **Static-role block:** cannot delete `admin` / `editor` / `member`. **In-use block:** cannot delete a role held by any user |
| `groups.py` | 7 | list (permission-filtered) / create / patch / delete, plus user-membership and document-membership add/remove. **In-use guard:** cannot delete a group with any user or document mapping |
| `settings.py` | 3 | get / patch singleton (admin), audit-log paginated read (admin) with `?user_id=` and `?action=` filters |
| `sync_jobs.py` | 4 | list (`?source_id=`) / get / retry (re-enqueue Celery task) / **SSE stream** (`/sync-jobs/{id}/stream` subscribes to `kg:sync:{job_id}:progress` Redis pub/sub via `app.sources.progress.subscribe_events`) |

**`main.py` wiring:**

- All 11 v1 routers registered under `/api/v1`
- Exception handlers for `RequestValidationError` (422 → E1 with `details.field_errors`) and generic `Exception` (500 → E15 with sanitized message + internal `request_id`)
- OpenAPI customization: title `"KnowGate API"`, version `"1.0.0"`, 7 tags (Auth, Sources, Documents, Query, Feedback, RBAC, Settings), `BearerAuth` security scheme (HTTPBearer, JWT)

**New env vars:** `RATE_LIMIT_PER_MINUTE_PER_IP` (default 600), `RATE_LIMIT_BYPASS_PATHS` (default `/health,/metrics,/api/v1/webhooks/*`).

**Tests:** 65 new API tests across 7 files (responses, users, roles, groups, documents, settings, sync_jobs). **292/292 total pass** (`pytest backend/tests/`). `ruff check` clean on all touched files.

**Known follow-ups (not blockers):**

- No streaming on `/query` 
- Semantic cache still key-based
- OpenAPI drift check not yet wired
- SSE `/sync-jobs/{id}/stream` is open to any authenticated user — should be admin-gated to prevent cross-group leakage of source/file metadata
- `RATE_LIMIT_LOGIN_PER_15MIN` constant exists but is not yet enforced by the middleware — login can be flooded up to the global 600/min ceiling

### feat: retrieval + LLM (query pipeline)

User-facing query path is live: cache → embed → hybrid search (vector + PG FTS + RRF) → rerank → LLM answer with numbered citations. The semantic cache, circuit-breaker fallback, and per-language no-result messages round it out.

**Retrieval + LLM modules (`backend/app/retrieval/`):**

- `query_embedder.py` — `embed_query_cached(text)` reuses the bge-m3 model from the ingestion pipeline; caches the result in Redis (`kg:query:embed:{sha256}`, 5 min TTL)
- `hybrid_search.py` — `search_vector` (Qdrant cosine with `group_ids ∈ user.groups` + `status=active` filter, top-20), `search_keyword` (PG FTS on the GIN-indexed `chunks.tsv` column, joined with `document_groups` for permission filter, falls back to `ILIKE` on non-PG), `merge_rrf` (Reciprocal Rank Fusion, k=60, dedupes by `chunk_id`, marks `retrieval_source="both"`), `hydrate_text_from_db` (fills in `text` for vector-only candidates from PG), `HybridSearcher` (orchestrator class)
- `reranker.py` — `BGEReranker` wraps `sentence_transformers.CrossEncoder(BAAI/bge-reranker-v2-m3)`, top-5 rerank; `prewarm_reranker()` worker startup hook
- `citation_builder.py` — `Citation` dataclass (index, chunk_id, doc_id, title, section_title, page, source, url, updated_at, language, score, snippet), `build_citations` maps `[N]` tokens to full citation objects, reports out-of-range `[N]` and ignored indices
- `answer_generator.py` — `AnswerGenerator` builds the prompt, calls the LLM (with a default `CircuitBreaker`-wired client), detects the "no answer" phrase, returns `GenerationResult` with text + citations + usage + cost
- `no_result.py` — `NoResultReason` enum (NO_RESULTS / ALL_DENIED / EMPTY_QUERY), `build_no_result_message` returns vi/en/zh localized message + suggestions
- `cache.py` — `SemanticCache` (24h TTL) reads/writes via the existing `app.cache.helpers.get_query_result` / `set_query_result` Redis helpers; key combines sha256(query_text) + sha256(sorted group_ids + language)
- `pipeline.py` — `QueryPipeline.run()` end-to-end orchestrator: empty check → user load → language detect → cache check → embed → hybrid search → no-result branches → rerank → doc metadata resolve → LLM → `Query` row persist → audit log → cache set. `run_query()` module-level convenience.

**LLM gateway (`backend/app/llm/`):**

- `client.py` — async httpx client to the LiteLLM proxy (`/v1/chat/completions`, OpenAI-compatible). Cost estimated from a per-model price table (gpt-4o-mini, gpt-4o, ollama/llama3; unknown → 0). `aclose()` for graceful shutdown.
- `prompts.py` — versioned system prompt (`KG_PROMPT_VERSION = "1.0.0"`, used as cache key prefix) enforcing: answer only from sources, numbered `[N]` citations, surface conflicts, no translation (D4), "no information" when sources are empty. Exports `NO_ANSWER_PHRASES` regex set (vi/en/zh) for the no-answer detector.
- `circuit_breaker.py` — primary → fallback model state machine (CLOSED / OPEN / HALF_OPEN, `StrEnum`). Process-local singleton. Configurable threshold (default 5) + cool-down (default 60s).

**FTS migration (`0003_add_chunk_fts`):**

- Adds `tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED` column on `chunks`
- GIN index `ix_chunks_tsv` on PG; B-tree fallback for SQLite test envs
- `simple` config (not `english`) so vi/zh diacritics are preserved; bge-m3 vector leg covers English stemming

**API endpoints (`backend/app/api/v1/`, user-gated):**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/query` | Ask a question; returns answer + citations + warnings + latency + cost. Rate-limited per user (default 30/min) |
| GET | `/query/history` | Caller's own past queries (paginated, newest first) |
| GET | `/query/{id}` | One of the caller's own queries (404 on others') |
| POST | `/feedback` | Submit rating (good/bad/source_missing) for one of the caller's queries; upserts by (query_id, user_id) |

**Routers registered** in `app/main.py` under `/api/v1`.

**New env vars:** none. Uses existing `LITELLM_HOST`, `LITELLM_PORT`, `LITELLM_MASTER_KEY`, `LITELLM_DEFAULT_MODEL`, `LITELLM_FALLBACK_MODEL`, `EMBEDDING_CACHE_TTL`, `RATE_LIMIT_QUERY_PER_MINUTE`.

**Tests:** 61 new retrieval + LLM unit tests across 9 files. **227/227 total pass** (`pytest backend/tests/`). `ruff check` clean on all touched files.

### feat: ingestion pipeline (parse + chunk + embed + index)

End-to-end ingestion pipeline: documents are downloaded from MinIO, parsed with Unstructured, chunked with the heading-aware + recursive splitter, embedded with bge-m3, and bulk-upserted to Qdrant. Chunk rows are persisted in PG with the embedding model version so re-embed is always possible. The sync engine now enqueues an `ingest_doc_task` for every uploaded document; new sources are automatically indexed on the next sync.

**Pipeline modules (`backend/app/pipeline/`):**

- `parser.py` — Unstructured-backed `parse_bytes` / `parse_file`. Spills bytes to a temp file when a filename is provided so extension-based dispatch works. Heading depth capped at h3. Tables, lists, narrative text all collected into the current section. `EmptyDocumentError` for image-only PDFs.
- `lang_detect.py` — `langdetect` per chunk, whitelisted to vi / en / zh (everything else → `und`). `DetectorFactory.seed = 0` for reproducibility. Short text (< 50 chars) short-circuits.
- `tokenizer.py` — tiktoken cl100k_base with cached encoder.
- `chunker.py` — heading-aware: each section becomes one chunk if it fits, recursive char split otherwise (paragraph → sentence → word). 10% overlap between adjacent pieces. Default 512 target / 1024 max tokens.
- `embedder.py` — bge-m3 wrapper around sentence-transformers. Lazy thread-safe model load. `embed_batch` returns float32 `np.ndarray` (N, 1024). `aembed_batch` runs the sync call in a thread. `prewarm_embedder` is the worker startup hook. `model_version()` returns `"bge-m3-v1.0.0"` (stored in `chunks.embedding_model`).
- `indexer.py` — `ingest_document(doc_id)` orchestrator: download → parse → chunk → embed → bulk upsert to Qdrant → upsert Chunk rows → mark Document ACTIVE. Idempotent (deterministic UUID v5 from `(doc_id, chunk_index)`). Marks FAILED on empty doc / parse error / embed error / Qdrant outage; never persists orphan chunks.

**Qdrant indexer extension (`backend/app/vector/indexer.py`):**

- `upsert_chunks_bulk(client, points, batch_size=500)` — batched writes for the ingest pipeline
- `make_point_id(doc_id, chunk_index)` — public deterministic UUID v5 (re-indexed doc → same Qdrant point IDs)
- `BULK_BATCH_SIZE = 500` constant

**Celery tasks (`backend/app/tasks/ingest.py`):**

- `ingest_doc_task(doc_id)` — entry point; 3 retries with 60s delay; "not found" / "already active" are no-retry cases
- `reembed_all_task(model_version=None)` — full re-embed sweep; batches of 256 chunks to bound memory
- `reembed_one_task(chunk_id)` — admin debug
- `@worker_init` signal handler pre-warms the embedder in every worker process
- `app.celery_app.include` now lists both `app.tasks.sync` and `app.tasks.ingest`

**Sync engine wiring (`backend/app/sources/sync.py`):**

- After a successful MinIO upload, sync engine enqueues `ingest_doc_task.delay(doc_row_id)`
- Broker outage is best-effort: the Document row is in `DISCOVERED` and the next scheduled sync (or an admin retry) will re-enqueue
- `_upsert_document` now returns the row id

**Schema-drift fix:** Migration `0002_add_source_webhook_fields.py` adds the 4 source columns added by the source-connectors work block. Required for fresh `make up`.

**Model pre-warm + load script:**

- `backend/scripts/load_bge_model.py` — offline downloader for air-gapped envs (`python -m scripts.load_bge_model`)
- Worker auto-prewarms via `worker_init` signal (no manual setup when network is available)

**New env vars:** none. `EMBEDDING_MODEL_NAME`, `EMBEDDING_DIM`, `EMBEDDING_DEVICE`, `EMBEDDING_BATCH_SIZE` are the standard embedding settings (read from `app.config.Settings`).

**Tests:** 72 new pipeline unit tests across 7 files (tokenizer, lang_detect, parser, chunker, embedder, vector_indexer, indexer orchestrator, ingest tasks). **166/166 total pass** (`pytest backend/tests/`). `ruff check` clean on all touched files.

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
