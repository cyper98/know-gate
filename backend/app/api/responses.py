"""Standard API response models + error code enum.

All API responses follow one of:
- Success:  { data, meta? }                       — direct, no wrapper
- Error:    { error: { code, message, details? } } — consistent shape

Success responses are Pydantic models exposed via `response_model=` in
the router. Error responses are constructed by `app.api.errors.to_error_response`
so handlers can raise `HTTPException` and the global exception handler
will re-shape them to the standard format.

Why "data" + "meta" instead of nested envelope:
- Simpler to read (one less indent)
- Direct Pydantic models per endpoint keep the OpenAPI clean
- Error envelope is consistent across endpoints
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# === Error codes (E1-E15) ===
# Cataloged in `docs/.../api/error-codes.md`.
# Concise identifier used in `error.code` so clients can branch on it
# without parsing the human-readable message.

class ErrorCode:
    """Error code catalog (stable string IDs for client branching)."""

    # Generic
    INTERNAL = "E1"            # 500 — unhandled exception
    BAD_REQUEST = "E2"         # 400 — validation failed
    UNAUTHORIZED = "E3"        # 401 — missing/invalid token
    FORBIDDEN = "E4"           # 403 — permission denied
    NOT_FOUND = "E5"           # 404 — resource not found
    CONFLICT = "E6"            # 409 — state conflict
    RATE_LIMITED = "E7"        # 429 — rate limit exceeded
    SERVICE_UNAVAILABLE = "E8" # 503 — upstream/downstream fail

    # Domain-specific
    PERMISSION_DENIED_DATA = "E9"     # data-level access denied (no docs in any group)
    NO_ANSWER = "E10"                 # search returned no answer
    EXTERNAL_API_ERROR = "E11"        # Drive/Notion/SMTP/LLM provider error
    INVALID_STATE = "E12"             # operation not allowed in current state
    QUOTA_EXCEEDED = "E13"            # usage cap reached
    DEPRECATED = "E14"                # endpoint deprecated
    UNPROCESSABLE = "E15"             # 422 — semantic validation failed


# === Schemas ===

class ErrorDetail(BaseModel):
    """Inner error payload returned in every error response."""

    code: str = Field(
        description="Stable error code (e.g., E4). Clients can branch on this."
    )
    message: str = Field(
        description="Human-readable, localized when possible. May include hints."
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured context (e.g., field-level validation errors).",
    )


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    error: ErrorDetail


class Meta(BaseModel):
    """Optional meta block for paginated list responses."""

    total: int | None = Field(default=None, ge=0, description="Total items (omitted if too expensive)")
    next_cursor: str | None = Field(
        default=None, description="Opaque cursor for the next page; absent = last page"
    )
    limit: int | None = Field(default=None, ge=1, le=100)


class Page[T](BaseModel):
    """Generic page wrapper for list endpoints.

    Use via `Page[UserResponse]` in a router's response_model. We keep the
    list at the top level (`data`) so the JSON is `{"data": [...], "meta": {...}}`.
    """

    data: list[T]
    meta: Meta = Field(default_factory=Meta)
