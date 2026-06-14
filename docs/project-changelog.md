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
  - 2026-06-14 | manual | initial changelog with auth + rbac entry
---

# KnowGate — Project Changelog

> Detailed record of significant changes, features, and fixes shipped to the codebase.
> Public-facing release notes live here; internal task tracking stays local.
> Newest entries on top. Format: `<date> | <scope> | <summary>`.

## Unreleased

- _Nothing yet._

## 2026-06-14

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
