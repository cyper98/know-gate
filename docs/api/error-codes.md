---
type: api-error-codes
status: active
created: 2026-06-14
updated: 2026-06-14
owner: "@seang"
tags: [api, errors, know-gate]
links:
  - "[[docs/system-architecture.md]]"
  - "[[docs/codebase-summary.md]]"
  - "[[README.md]]"
changelog:
  - 2026-06-14 | /cook | cataloged E1-E15 from app/api/responses.py
---

# KnowGate — REST API Error Codes

> Stable error code catalog returned in the standard error envelope.
>
> **Envelope shape (all errors):**
> ```json
> { "error": { "code": "E4", "message": "Permission denied", "details": { ... } } }
> ```
>
> `code` is a stable string ID (E1-E15) for client branching. `message` is
> human-readable and may be localized. `details` is optional structured
> context (e.g. field-level validation errors).
>
> Implemented in `backend/app/api/responses.py` (`ErrorCode` class) and
> `backend/app/api/errors.py` (mapping + envelope construction).

## Generic codes

| Code | HTTP | Constant | When raised | Example message |
|------|------|----------|-------------|-----------------|
| **E1**  | 500 | `INTERNAL`            | Unhandled exception caught by the global handler; traceback logged server-side, client gets a sanitized message | `"An internal error occurred. The incident has been logged."` |
| **E2**  | 400 | `BAD_REQUEST`         | Generic 4xx from `HTTPException` (without a more specific code); also the code for Pydantic `RequestValidationError` mapped at 422 | `"Request validation failed"` (with `details.errors[]` listing `loc` / `msg` / `type` per field) |
| **E3**  | 401 | `UNAUTHORIZED`        | Missing, malformed, expired, or revoked JWT (jti blacklist) | `"Not authenticated"` |
| **E4**  | 403 | `FORBIDDEN`           | Authenticated user lacks the required `Permission` for the endpoint (role → permission check failed) | `"Permission denied"` |
| **E5**  | 404 | `NOT_FOUND`           | Resource (doc / source / user / role / group / sync-job / query) does not exist or is hidden behind the user's access groups | `"Document not found"` |
| **E6**  | 409 | `CONFLICT`            | State conflict: duplicate key (email / slug), trying to delete a role still in use, etc. | `"User with this email already exists"` |
| **E7**  | 429 | `RATE_LIMITED`        | Global IP throttle middleware (default 600 req/min/IP) or a per-endpoint sliding-window limit (login 5/15min, query 30/min, etc.) | `"Too many requests from this IP: 642 in the last 60s (limit 600/min). Slow down and try again shortly."` (response includes `Retry-After` and `X-RateLimit-*` headers) |
| **E8**  | 503 | `SERVICE_UNAVAILABLE` | A required backend is down at request time (PG / Qdrant / Redis / MinIO), surfaced by `/ready` or a request that hits a missing dependency | `"Service unavailable"` |

## Domain-specific codes

| Code | HTTP | Constant | When raised | Example message |
|------|------|----------|-------------|-----------------|
| **E9**  | 403 | `PERMISSION_DENIED_DATA` | Query / search returned results but **all** are outside the user's access groups; intentionally distinct from E4 (RBAC gate) so clients can render a "no permission" state with the hidden count | `"No accessible documents matched. You are not in any group that has access to the matching results."` (with `details: {matched: N}` — count only, never titles, to avoid leaking) |
| **E10** | 200 | `NO_ANSWER`            | Query pipeline completed but the LLM said "no information" (matched `NO_ANSWER_PHRASES` regex in vi/en/zh); returned as a normal 200 with a structured `no_result` block, not as an HTTP error | `200 OK` body: `{ "data": { "answer": null, "no_result": { "reason": "NO_RESULTS", "message": "...", "suggestions": [...] } } }` |
| **E11** | 502 / 504 | `EXTERNAL_API_ERROR` | Upstream provider call failed: Google Drive / Notion / SMTP / LLM (LiteLLM) returned a 5xx, timed out, or returned a malformed response | `"External API request failed: litellm 504"` |
| **E12** | 409 | `INVALID_STATE`        | Operation not allowed in the current state of the resource (e.g. retrying a `completed` sync job, deleting an `active` source) | `"Cannot retry a job in state 'completed'"` |
| **E13** | 402 | `QUOTA_EXCEEDED`       | Per-user / per-tenant usage cap reached (queries/day, indexed docs, etc.) | `"Monthly query quota exceeded"` |
| **E14** | 410 | `DEPRECATED`           | Endpoint reached end-of-life; client should migrate to the successor endpoint advertised in the `Deprecation` / `Sunset` response headers | `"Endpoint deprecated; use /api/v2/sources"` |
| **E15** | 422 | `UNPROCESSABLE`        | Request was syntactically valid but semantically rejected (custom domain rule, not Pydantic field validation) | `"Cannot promote a user to admin while they are pending email verification"` |

## Error response examples

**Generic 4xx (from `HTTPException` with `detail` string):**
```json
{ "error": { "code": "E5", "message": "Document not found" } }
```

**Rich error (router uses `api_error(...)` helper):**
```json
{
  "error": {
    "code": "E4",
    "message": "Permission denied",
    "details": { "required": "manage_sources", "actual_role": "member" }
  }
}
```

**Pydantic validation failure (auto-mapped to E2 with field details):**
```json
{
  "error": {
    "code": "E2",
    "message": "Request validation failed",
    "details": {
      "errors": [
        { "loc": ["body", "email"], "msg": "value is not a valid email address", "type": "value_error.email" }
      ]
    }
  }
}
```

**Rate limit (E7) with retry headers:**
```
HTTP/1.1 429 Too Many Requests
Retry-After: 60
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 0

{ "error": { "code": "E7", "message": "Too many requests from this IP: 642 in the last 60s (limit 600/min). Slow down and try again shortly." } }
```

## Client guidance

- **Branch on `error.code`, not on `error.message`** — the message is human-readable and may be localized.
- **`details` is optional and shape varies** — only parse fields documented per endpoint.
- **Pydantic errors always arrive as E2** (with `details.errors[]`) regardless of whether the endpoint is on 400 or 422 routes. Check `details.errors[].loc` for field paths.
- **E9 (`PERMISSION_DENIED_DATA`) is a successful authorization, denied data** — distinct from E4 (`FORBIDDEN`, which is an authorization gate). E9 may still 200 with a structured body; check the API doc for the endpoint.
- **E10 (`NO_ANSWER`) is HTTP 200** — it's a "the system worked, the answer is no" outcome, not an error. Treat as a successful response with `data.no_result` populated.

## See also

- Architecture: [[docs/system-architecture.md]]
- Source: `backend/app/api/responses.py`, `backend/app/api/errors.py`
- API surface inventory: architecture doc §5 (internal)
