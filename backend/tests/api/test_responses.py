"""Unit tests for the common API utilities (responses, pagination, errors).

These don't need a database — they test pure helpers + Pydantic models.
The router-level tests in `test_documents.py` etc. cover the integration
with `get_session_factory()` and friends.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.errors import api_error, to_error_response
from app.api.pagination import (
    PageParams,
    decode_cursor,
    decode_role_cursor,
    encode_cursor,
    encode_role_cursor,
)
from app.api.responses import ErrorCode, ErrorDetail, ErrorResponse, Meta, Page

# === Responses ===

def test_error_response_envelope_shape() -> None:
    """Error responses must be `{"error": {"code", "message", "details?"}}`."""
    err = ErrorResponse(error=ErrorDetail(code="E4", message="Forbidden"))
    payload = err.model_dump()
    assert payload == {"error": {"code": "E4", "message": "Forbidden", "details": None}}


def test_meta_optional_next_cursor() -> None:
    """`next_cursor` is absent (None) on the last page — clients use absence, not null."""
    m = Meta(limit=20)
    assert m.next_cursor is None
    assert m.total is None


def test_page_wraps_list() -> None:
    """Page[T] exposes `data` + `meta` per the standard format."""
    p = Page[int](data=[1, 2, 3], meta=Meta(limit=20))
    assert p.data == [1, 2, 3]
    assert p.meta.limit == 20


def test_error_code_stable_ids() -> None:
    """ErrorCode strings are part of the public API; never rename them."""
    assert ErrorCode.INTERNAL == "E1"
    assert ErrorCode.NOT_FOUND == "E5"
    assert ErrorCode.RATE_LIMITED == "E7"
    assert ErrorCode.PERMISSION_DENIED_DATA == "E9"
    assert ErrorCode.DEPRECATED == "E14"


# === Pagination ===

def test_cursor_roundtrip() -> None:
    """Encode → decode must produce the original (timestamp, id)."""
    now = datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
    cursor = encode_cursor(now, "abc-123")
    ts, item_id = decode_cursor(cursor)
    assert ts == now
    assert item_id == "abc-123"


def test_cursor_decode_rejects_garbage() -> None:
    """Invalid base64 / wrong shape → ValueError so the router can return 400."""
    with pytest.raises(ValueError):
        decode_cursor("not-a-real-cursor!!!")


def test_role_cursor_roundtrip() -> None:
    """Role cursor uses a name+id shape (alphabetical sort)."""
    cur = encode_role_cursor("admin", "uuid-1")
    n, i = decode_role_cursor(cur)
    assert n == "admin"
    assert i == "uuid-1"


def test_page_params_limit_bounds() -> None:
    """PageParams enforces 1 <= limit <= 100"""
    PageParams(limit=1)
    PageParams(limit=100)
    PageParams()  # default 20
    with pytest.raises(ValidationError):
        PageParams(limit=0)
    with pytest.raises(ValidationError):
        PageParams(limit=101)


def test_cursor_handles_subsecond_precision() -> None:
    """ISO format preserves microseconds; roundtrip is exact."""
    now = datetime(2026, 6, 14, 12, 0, 0, 123456, tzinfo=UTC)
    cursor = encode_cursor(now, "x")
    ts, _ = decode_cursor(cursor)
    assert ts == now


# === Errors ===

def test_api_error_returns_structured_detail() -> None:
    """`api_error` returns an HTTPException with a dict detail (so the
    error handler can extract `code` + `message` for the envelope)."""
    exc = api_error(404, ErrorCode.NOT_FOUND, "User not found")
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 404
    assert isinstance(exc.detail, dict)
    assert exc.detail["code"] == "E5"
    assert exc.detail["message"] == "User not found"


def test_api_error_preserves_details() -> None:
    """Optional `details` dict is passed through to the error envelope."""
    exc = api_error(
        400, ErrorCode.BAD_REQUEST, "Invalid input",
        details={"field": "email", "reason": "malformed"},
    )
    assert exc.detail["details"] == {"field": "email", "reason": "malformed"}


def test_to_error_response_handles_human_detail() -> None:
    """An HTTPException raised with a plain string detail keeps the message."""
    exc = HTTPException(status_code=404, detail="Sync job not found")
    status_code, body = to_error_response(exc)
    assert status_code == 404
    assert body.error.code == ErrorCode.NOT_FOUND
    assert body.error.message == "Sync job not found"


def test_to_error_response_handles_dict_detail() -> None:
    """An HTTPException from `api_error(...)` exposes code + message via the envelope."""
    exc = api_error(409, ErrorCode.CONFLICT, "Email already exists")
    status_code, body = to_error_response(exc)
    assert status_code == 409
    assert body.error.code == ErrorCode.CONFLICT
    assert body.error.message == "Email already exists"


def test_to_error_response_unhandled_returns_500() -> None:
    """Uncaught exceptions collapse to E1 (sanitized, no internals leaked)."""
    exc = RuntimeError("internal SQL details…")
    status_code, body = to_error_response(exc)
    assert status_code == 500
    assert body.error.code == ErrorCode.INTERNAL
    assert "internal error" in body.error.message.lower()
    assert "SQL" not in body.error.message  # no leak


# === Sanity: cursor text is url-safe ===

def test_cursor_is_url_safe() -> None:
    """Encoded cursors must be safe to drop into a query string unescaped."""
    now = datetime.now(UTC)
    cursor = encode_cursor(now, "id-with+/=")
    # url-safe base64 uses '-' and '_' instead of '+' and '/'
    assert "+" not in cursor
    assert "/" not in cursor


# === Meta: total + next_cursor coexistence ===

def test_meta_with_total() -> None:
    """Some endpoints can emit a total count (e.g., the dashboard)."""
    m = Meta(limit=20, total=143, next_cursor="abc")
    assert m.total == 143
    assert m.next_cursor == "abc"


# === Roundtrip datetime with timezone ===

def test_cursor_roundtrip_naive_datetime() -> None:
    """Naive datetimes are accepted by encode (we always UTC on read)."""
    naive = datetime(2026, 6, 14, 0, 0, 0)
    cursor = encode_cursor(naive, "x")
    ts, _ = decode_cursor(cursor)
    # No tz info on the decoded value either (encode uses isoformat)
    assert ts == naive


def test_cursor_roundtrip_with_timedelta() -> None:
    """A long offset roundtrips through a 24h + cursor."""
    now = datetime.now(UTC)
    future = now + timedelta(days=365)
    cur = encode_cursor(future, "id")
    ts, _ = decode_cursor(cur)
    assert (ts - now).days == 365
