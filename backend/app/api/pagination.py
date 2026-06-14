"""Cursor-based pagination helpers.

Cursor strategy:
- Encode `(created_at, id)` into an opaque base64 URL-safe string.
- Sort by `created_at DESC, id DESC` (newest first); stable secondary sort
  by UUID ensures no ties even at sub-millisecond granularity.
- Decode cursor → WHERE (created_at, id) < (cursor_ts, cursor_id) for the
  "next page" query.

Why cursor over offset:
- Stable under concurrent inserts (offset shifts when new rows arrive).
- Cheap on indexed columns (no count(*) scan, just a where+limit).
- Matches the query history / audit log pattern (append-only, newest first).

Limit defaults: 20, max 100.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    """Standard query-string params for cursor-paginated list endpoints.

    Routers accept these via `Depends()` and pass them to `paginate_query`.
    """

    cursor: str | None = Field(
        default=None,
        description="Opaque cursor returned in the previous response's `meta.next_cursor`.",
    )
    limit: int = Field(
        default=20, ge=1, le=100,
        description="Page size (default 20, max 100).",
    )


def encode_cursor(created_at: datetime, item_id: str) -> str:
    """Encode a (timestamp, id) pair as an opaque URL-safe base64 string."""
    payload = json.dumps(
        {"ts": created_at.isoformat(), "id": item_id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode an opaque cursor back into (datetime, id). Raises ValueError on bad input."""
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["ts"]), payload["id"]
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        raise ValueError(f"Invalid cursor: {cursor!r}") from e


def next_cursor_from_rows(
    rows: list[Any],
    *,
    ts_attr: str = "created_at",
    id_attr: str = "id",
    limit: int,
) -> str | None:
    """If we returned a full page, assume more exist and emit a next-cursor.

    Callers should always pair this with a `limit+1` query and slice the
    extra row, so we know if the page is exactly `limit` because there's
    a next page, or exactly `limit` because we just barely fit.
    """
    if len(rows) > limit:
        last = rows[limit - 1]
        return encode_cursor(getattr(last, ts_attr), getattr(last, id_attr))
    return None


# === Name+ID cursor (for lexicographic sort like roles.name) ===

def encode_role_cursor(name: str, item_id: str) -> str:
    """Encode a (name, id) pair as an opaque URL-safe base64 cursor."""
    payload = json.dumps({"n": name, "id": item_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_role_cursor(cursor: str) -> tuple[str, str]:
    """Decode an opaque name+id cursor. Raises ValueError on bad input."""
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw)
        return str(payload["n"]), str(payload["id"])
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        raise ValueError(f"Invalid role cursor: {cursor!r}") from e
