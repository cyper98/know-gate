---
type: project-overview-pdr
status: draft
created: 2026-06-14
updated: 2026-06-14
owner: "@seang"
tags: [pdr, know-gate, mvp, rag]
links:
  - "[[docs/system-architecture.md]]"
  - "[[docs/code-standards.md]]"
  - "[[docs/deployment-guide.md]]"
  - "[[docs/codebase-summary.md]]"
  - "[[README.md]]"
changelog:
  - 2026-06-14 | manual | marked Source Connectors as shipped: BaseSourceConnector ABC + Google Drive + Notion; sync engine with Redis pub/sub progress; Celery task + Beat; source CRUD API + Drive webhook; Source model webhook fields
  - 2026-06-14 | manual | marked Auth + RBAC capability as shipped; added argon2id, OAuth PKCE, AES-256-GCM, ClientIPMiddleware, audit log details
  - 2026-06-14 | manual | removed all development-stage wording + roadmap file (docs are system-only)
  - 2026-06-14 | manual | removed references to internal brainstorm + plan files (kept on local only)
  - 2026-06-14 | manual | initial PDR draft
---

# KnowGate — Project Overview & PDR

> Open-source (MIT) RAG-based internal knowledge search and Q&A platform. Self-hosted per company. Multilingual (VI/EN/ZH), permission-aware, citation-backed.

## 1. Problem

Modern companies accumulate internal knowledge across Drive, Notion, Confluence, GitHub, Slack, and email. Employees waste time searching for the right policy, the latest pricing, the most recent spec, or the right person to ask. Generic consumer chat tools (ChatGPT, Notion AI) cannot index private data safely. Enterprise search (Glean, Confluence AI) lock customers into vendor stacks and US-based data processing, which is a non-starter for many regulated teams.

KnowGate closes that gap: a self-hostable, open-source, multilingual RAG platform that respects existing permission boundaries (user → access group → document) and surfaces answers with citations the user can verify.

## 2. Users

Six user types identified from initial design sessions:

| User Type | Primary Need |
|-----------|--------------|
| Nhân viên mới (new hire) | Find onboarding docs, policies, processes quickly |
| Support / Customer Success | Look up CS policies, ticket history, FAQs |
| Sales | Find current pricing, case studies, decks by region |
| Engineering / Product | Find technical docs, past design decisions, RFCs, specs |
| Legal / Finance / HR / Ops | Find official policies, approval workflows, contracts |
| Ban quản lý (governance) | Dashboard of stale, missing, or bottleneck knowledge |

Pilot audience: open-source community contributors plus engineering dev dogfooding during the build.

## 3. MVP Scope (P0)

Locked from initial design sessions. Internal implementation planning is tracked privately (not part of this public repo).

**Ingest:**
- **Source Connectors** *(shipped)* — Google Drive + Notion via `BaseSourceConnector` ABC; OAuth (Drive) or integration token (Notion); per-source encrypted config (`config_encrypted` AES-256-GCM); polling via Celery Beat every 5 min (`SYNC_INTERVAL_MINUTES`); Drive push notifications on `POST /api/v1/webhooks/google-drive` (verifies `X-Goog-Channel-Token`, enqueues `sync_source_task(triggered_by="webhook")`); sync engine persists raw bytes to MinIO under `{type}/{source_id}/{doc_id}` and upserts `Document` row in `discovered` status; progress events published to Redis pub/sub `kg:sync:{job_id}:progress` for SSE; max 3 concurrent sync jobs per instance (`SYNC_MAX_CONCURRENT`), batch 100 docs (`SYNC_BATCH_SIZE`), skip docs over 50 MB (`MAX_DOC_SIZE_MB`); auth failure marks source `auth_failed` and pauses syncs; 5-min Beat schedule
- **Document parsers** *(shipped)* — Unstructured-backed `parse_bytes` / `parse_file` for PDF / DOCX / PPTX / XLSX / MD / TXT / HTML; heading depth capped at h3; tables, lists, narrative text all collected into the current section; image-only PDFs raise `EmptyDocumentError`
- **Chunking by heading/section/paragraph** *(shipped)* — `chunk_by_sections` (in `app.pipeline.chunker`); default 512 target / 1024 max tokens, 10% overlap between adjacent pieces; recursive char fallback (paragraph → sentence → word) for sections that exceed the cap
- **Embedding (bge-m3 self-host)** *(shipped)* — `app.pipeline.embedder` wraps sentence-transformers; 1024-dim, L2-normalized, batched (default 8 on CPU, 32 on CUDA via `EMBEDDING_BATCH_SIZE`); worker pre-warms on `worker_init` signal; `model_version()` returns `bge-m3-v1.0.0` and is stored in `chunks.embedding_model`
- **Qdrant vector index** *(shipped)* — bulk upsert (500 points / batch) into the `chunks` collection with payload `{doc_id, group_ids, language, status, chunk_index, section_title, indexed_at, source, source_id}`; deterministic UUID v5 from `(doc_id, chunk_index)` for idempotent re-index
- **Language detection per chunk** *(shipped)* — `langdetect` whitelisted to vi / en / zh (everything else → `und`); `DetectorFactory.seed = 0` for reproducibility
- **Ingest Celery task** *(shipped)* — `ingest_doc_task(doc_id)` runs end-to-end with 3 retries; sync engine auto-enqueues after a successful upload; `reembed_all_task` / `reembed_one_task` for model upgrades
- **Sync job lifecycle** *(shipped)* — `queued` → `running` → `completed` / `partial` / `failed`; `triggered_by` = `manual` / `scheduled` / `webhook`; rows in `sync_jobs` table
- **Document status** *(shipped)* — `active` / `outdated` / `deprecated` / `archived` / `deleted`; tombstones from `list_changes(is_deleted=True)` mark `Document.status=deleted`; ingest sets `active` with `indexed_at` on success, `failed` with `error_message` on empty/parse/embed/qdrant errors

**Retrieve + answer:**
- **Hybrid search (vector + keyword)** *(shipped)* — Qdrant cosine (with `group_ids ∈ user.groups` + `status=active` filters) in parallel with PostgreSQL FTS on the GIN-indexed `chunks.tsv` column; merged with Reciprocal Rank Fusion (k=60, top-20); permission filter applied at both layers + post-retrieval
- **Reranker (bge-reranker-v2-m3)** *(shipped)* — sentence-transformers CrossEncoder; reranks top-20 to top-5; pre-warmed at worker startup
- **LLM answer generation with numbered citations** *(shipped)* — LiteLLM proxy (gpt-4o-mini default, ollama/llama3 fallback) via a `CircuitBreaker` (5-failure threshold, 60s cool-down); prompt versioned as `KG_PROMPT_VERSION`; cost estimated per model; answer text + structured `Citation` objects (title, section, page, source provider, last_updated, presigned URL, snippet)
- **Query language auto-detect and user-pick** *(shipped)* — `langdetect` (vi/en/zh whitelist); user pref wins
- **Answer always in source language (no translation per D4)** *(shipped)* — the prompt explicitly forbids translation; `NO_ANSWER_PHRASES` regex detects the "no info" signal in all 3 languages
- **Semantic cache (24h TTL)** *(shipped)* — Redis-backed; key = sha256(query_text) + sha256(sorted group_ids + language); prevents cross-user leakage
- **No-result handler** *(shipped)* — empty index → E5 message + popular-doc suggestions; all-denied → E9 message with hidden count (no titles — leak defense)

**Auth + RBAC:** *(shipped)*
- Email/password (bootstrap) + Google/GitHub OAuth (PKCE) + magic link
- JWT (RS256, 15-min access + 30-day refresh with rotation, `jti` revocation)
- Passwords: argon2id per OWASP 2024 params; transparent rehash on parameter drift
- 3-role RBAC: admin (all) / editor (view + edit metadata) / member (view)
- 9 permission gates: view_doc, edit_doc_metadata, delete_doc, manage_users, manage_roles, manage_groups, manage_sources, manage_settings, invite_user, view_audit_log
- Access group model (user → group, doc → group, AND-logic permission filter)
- `ClientIPMiddleware` reads `X-Forwarded-For` for audit + rate limit (sliding-window in Redis)
- AES-256-GCM encryption for OAuth tokens at rest (`KG_ENCRYPTION_KEY`)
- `audit_log` table: append-only, best-effort, non-blocking writers, immutable by convention

**UX:**
- Next.js 14 web UI + Python CLI + REST API
- i18n UI (VI + EN, default EN)
- Feedback button (good / bad / source-missing)
- Admin dashboard: sync log, user mgmt, permission config, query log
- Audit log for permission changes (immutable)

## 4. Non-Goals (MVP)

- Confluence / GitHub / Jira / Slack / Email connectors (P2)
- Cross-language answer translation (removed per brainstorm D4)
- Nested role hierarchy (flat 3-role only per OQ-7)
- AI agent auto-suggesting doc updates (P2)
- Model router / cost governance dashboard (P2)
- PII detection and redaction (P2)
- Browser extension / VS Code plugin (P2)

## 5. Success Criteria

From initial design sessions. Final lock happens during business requirements sign-off.

| Metric | Target |
|--------|--------|
| Adoption | ≥ 10 self-hosted production instances in first 6 months |
| Retrieval quality | Top-5 retrieval accuracy ≥ 80% on pilot eval dataset |
| Latency | P95 query < 5s with self-hosted LLM, < 3s with cloud LLM |
| User satisfaction | Feedback rating ≥ 70% "good" |
| Coverage | 90% of pilot docs indexed successfully |
| Performance | ≥ 100 concurrent users per instance |
| Community | ≥ 5 external contributors in first 6 months |

## 6. Constraints & Assumptions

- **License:** MIT, open-source.
- **Hosting model:** self-hosted per company, single binary or docker-compose install.
- **Pilot team size:** 1 dev full-time → ~4 weeks to MVP demo; 2-3 devs parallel → ~2 weeks.
- **LLM provider:** OpenAI default (gpt-4o-mini) via LiteLLM proxy, optional Ollama self-host fallback.
- **Embedding:** bge-m3 self-hosted, free, multilingual (no per-token cost).
- **Permission invariant:** chunks only pass to LLM if `user.groups ∩ doc.groups` is non-empty (defense in depth at 3 layers: API filter, Qdrant payload filter, post-retrieval check).
- **Multilingual scope:** minimum VI + EN, ZH if bge-m3 quality allows.

## 7. Risks

Top three risks to track:

- **R1 (Adoption):** open-source RAG competes with Notion AI, Confluence AI, Glean — pivot on self-host + open source + VI/EN/ZH multilingual.
- **R3 (Permission misconfig):** data leak risk. Mitigate with permission templates, dry-run mode, audit log, admin training doc.
- **R5 (Scope creep):** 5 flows × 2 connectors × full RBAC × i18n is a lot. Prioritize F3 (user query) first; cut F4 detail; defer Slack share to P1.

## 8. Related Documents

- Architecture: [[docs/system-architecture.md]]
- Code Standards: [[docs/code-standards.md]]
- Deployment: [[docs/deployment-guide.md]]
- Codebase summary: [[docs/codebase-summary.md]]
- README: [[README.md]]
