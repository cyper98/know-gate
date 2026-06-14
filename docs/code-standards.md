---
type: code-standards
status: draft
created: 2026-06-14
updated: 2026-06-14
owner: "@seang"
tags: [code-standards, know-gate, python, typescript, docker]
links:
  - "[[docs/system-architecture.md]]"
  - "[[README.md]]"
changelog:
  - 2026-06-14 | manual | removed all development-stage wording (docs are system-only)
  - 2026-06-14 | manual | removed references to internal architecture/plan files
  - 2026-06-14 | manual | initial code standards
---

# KnowGate — Code Standards

> Established during initial setup. Source of truth for code style, tooling, and conventions.

## 1. Guiding Principles

- **YAGNI** — don't build what we don't need yet.
- **KISS** — pick the boring solution.
- **DRY** — one source of truth per fact; no copy-paste config.
- **Env-first** — no hardcoded values; never provide fallback defaults for required env vars.
- **Defense in depth** for security boundaries (auth, permission, encryption).

## 2. Python (backend, CLI, scripts)

**Version:** Python 3.12 (strict, `<3.13`).

**Tooling:**
- Package manager: `pip` (or `uv` if dev prefers); `pyproject.toml` is the single source of truth.
- Lint + format: `ruff` (replaces flake8 + isort + black).
- Type check: `mypy` strict mode.
- Test: `pytest` + `pytest-asyncio` + `pytest-cov`.

**Style (configured in `backend/pyproject.toml`):**
- Line length: 100.
- Lint rule sets: `E, W, F, I, B, C4, UP, N, SIM, RUF`.
- Per-file ignores: `tests/*` skip `S101` (assert), `B011`; `scripts/*` skip `T201` (print).
- Type hints required on all public functions; `disallow_untyped_defs = true`.
- pytest coverage threshold: `--cov-fail-under=80`.

**Async:** prefer `async def` for I/O-bound code (DB, HTTP, queue). Use SQLAlchemy 2 async sessions.

**Error handling:** catch narrow exception types, log with `structlog` context binding, re-raise with custom app exception classes. No bare `except:`.

**Naming:** snake_case modules/functions, PascalCase classes, UPPER_SNAKE_CASE constants. Module names self-documenting (kebab-case only for the file name on disk; Python import name stays snake_case equivalent).

## 3. TypeScript (frontend)

**Version:** Node 20 LTS, TypeScript 5.6+.

**Tooling:**
- Package manager: `npm` (pnpm optional).
- Lint: `eslint` + `eslint-config-next`.
- Format: `prettier` + `prettier-plugin-tailwindcss`.
- Type check: `tsc --noEmit` (strict mode).
- Test: Playwright (E2E).

**Style:**
- `tsconfig.json` `strict: true`.
- Components: function components, named exports.
- File names: kebab-case for non-component files (e.g. `query-api.ts`), PascalCase for React components (`QueryInput.tsx`).
- Hooks: `useXxx` convention; extract reusable hooks to `lib/hooks/`.
- State: Zustand for global, `useState` for local; TanStack Query for server state.
- Forms: Zod schema + react-hook-form (when added in the frontend).
- i18n: all user-facing strings via `next-intl`; never hardcode user-facing English in components.

**Async:** always `await` async calls; handle errors with try/catch + toast.

## 4. Docker

**Base images:**
- Backend: `python:3.12-slim`.
- Frontend: `node:20-alpine` (multi-stage).
- Infra: official images (postgres:16-alpine, redis:7-alpine, qdrant/qdrant, minio/minio).

**Required patterns:**
- **Multi-stage** builds (builder → runtime) to keep runtime image small.
- **Non-root user** in runtime stage (`UID 1001`, group `knowgate` or `nodejs`).
- **`HEALTHCHECK`** directive on every long-running service.
- **`EXPOSE`** port, never `publish` in Dockerfile (Compose handles).
- **BuildKit** syntax header (`# syntax=docker/dockerfile:1.7`) for cache mounts and modern features.
- `.dockerignore` per package to keep build context small.

**Compose:**
- All config from `.env` (no hardcoded values).
- Required env vars use `${VAR:?VAR required}` (fail fast at startup).
- Optional vars use `${VAR:-default}` only when truly optional and default is safe.
- `healthcheck` on every service; dependents use `condition: service_healthy`.
- Named volumes for data persistence; bind-mount only for source code (dev overlay).

## 5. Environment Variables

**Hard rules (from `.claude/rules/development-rules.md`):**
- **Never** hardcode URLs, credentials, ports, or keys in source code.
- **Never** provide fallback defaults for required env vars — the app must fail fast with a clear error if missing.
- **Atomic granularity:** never use a single long connection URL. Always split: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`. Same for Redis (`REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`), Qdrant (`QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_GRPC_PORT`, `QDRANT_API_KEY`), MinIO (`MINIO_ENDPOINT`, `MINIO_PORT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_BUCKET`), LiteLLM (`LITELLM_HOST`, `LITELLM_PORT`, `LITELLM_MASTER_KEY`).
- **Naming convention:** `<SCOPE>_<COMPONENT>_<FIELD>` (e.g. `DB_HOST`, `LITELLM_DEFAULT_MODEL`, `EMBEDDING_BATCH_SIZE`).
- **Secrets** (JWT private key, encryption key, OAuth client secret) live in `secrets/` (gitignored) or `.env` (gitignored), never in repo.
- **Required vs optional:** optional vars get a dev default in `.env.example`; required vars are documented as such in `.env.example` comments.

**Generator helper:** `make secrets` generates JWT RS256 key pair + 32-byte base64 encryption key.

## 6. File Organization

- **Kebab-case file names** with descriptive purpose; long names are OK (self-documenting for LLMs).
- **Module size:** keep individual code files under 200 lines; split when larger. Compose over inheritance; extract utilities; dedicated service classes for business logic.
- **Comments:** explain *why*, not *what*. Use docstrings on public functions (Python) and JSDoc on exported functions (TS).
- **One concept per file** when practical (e.g. one Celery task per file in `app/worker/tasks/`).

## 7. Logging & Observability

- **Structured JSON logging** via `structlog` (backend) with context binding (`logger.bind(user_id=...)`).
- **Log levels:** DEBUG for dev, INFO for prod default; never log secrets or PII.
- **Request tracing:** OpenTelemetry span per request, propagated to DB and HTTP calls.
- **Metrics:** Prometheus format at `/metrics` (API), custom counters/histograms for queue depth, query latency, sync progress.

## 8. Security

- **Passwords:** Argon2 (argon2-cffi); never log or return password hashes.
- **JWT:** RS256, 15-min access + 30-day refresh with rotation, `jti` claim for revocation.
- **Encryption:** symmetric AES via Fernet, key from `KG_ENCRYPTION_KEY` (32-byte base64) for sensitive config (OAuth tokens at rest).
- **Session cookie:** `HttpOnly`, `Secure`, `SameSite=Lax`.
- **API auth:** Bearer token in `Authorization` header.
- **Permission filter:** enforced at 3 layers (API, Qdrant payload, post-retrieval).
- **Input validation:** Pydantic v2 (BE) / Zod (FE) on every endpoint boundary.
- **Secrets in `.env`:** gitignored; never commit. CI uses dummy test values.

## 9. Testing

- **Unit:** pytest (BE), Vitest or jest (FE, when added).
- **Integration:** pytest + httpx for API routes (DB mocked or testcontainers).
- **E2E:** Playwright (FE).
- **Load:** k6.
- **Coverage threshold:** ≥ 80% on backend (`--cov-fail-under=80`).
- **Test naming:** `test_*.py` files, `Test*` classes, `test_*` functions.
- **Async tests:** `asyncio_mode = "auto"`; no `@pytest.mark.asyncio` boilerplate.

## 10. Git & Commits

- **Conventional commits:** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- **No AI references** in commit messages.
- **One focused concern per commit** — don't bundle unrelated changes.
- **Never commit secrets:** `.env`, `secrets/`, `*.pem`, `*.key` are gitignored.
- **Pre-commit:** run `make lint` locally before pushing; CI runs full pipeline (lint + type + test + build + docker validate).

## 11. CI Pipeline (`.github/workflows/ci.yml`)

Five jobs run on push to `main` and on PRs:

1. `backend-lint` — ruff check + ruff format check.
2. `backend-test` — pytest (test keypair injected via env).
3. `frontend-lint` — eslint + tsc --noEmit + prettier check.
4. `frontend-build` — next build.
5. `docker-validate` — `docker compose config --quiet` for base + dev overlay.
6. `ci-status` — summary gate; fails if any job fails.

CI is read-only on the filesystem (no push), no auto-deploy.

## 12. References

- Backend pyproject: `backend/pyproject.toml`
- Frontend package: `frontend/package.json`
- CI workflow: `.github/workflows/ci.yml`
- Compose base: `deploy/docker-compose.yml`
- Compose dev overlay: `deploy/docker-compose.dev.yml`
- Env template: `.env.example`
- Dev rules: [[.claude/rules/development-rules.md]]
