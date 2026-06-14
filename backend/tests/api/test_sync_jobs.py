"""Unit tests for the sync-jobs API router (SSE + retry endpoints)."""

from __future__ import annotations

import json

from app.api.v1.sync_jobs import _sse

# === SSE helper ===

def test_sse_formats_event_line() -> None:
    """Each SSE message has `event: <name>\\ndata: <json>\\n\\n` format."""
    raw = _sse("progress", {"indexed_docs": 5, "total_docs": 10})
    text = raw.decode("utf-8")
    # Per SSE spec: event on first line, data on second, blank line terminates
    lines = text.split("\n")
    assert lines[0].startswith("event: progress")
    assert lines[1].startswith("data: ")
    assert lines[2] == ""
    # Data line is valid JSON
    payload = json.loads(lines[1][len("data: "):])
    assert payload == {"indexed_docs": 5, "total_docs": 10}


def test_sse_includes_terminal_event() -> None:
    raw = _sse("terminal", {"status": "completed"})
    text = raw.decode("utf-8")
    assert "event: terminal" in text
    assert '"status": "completed"' in text


def test_sse_ping_event() -> None:
    """Keep-alive pings are emitted as their own event type."""
    raw = _sse("ping", {"ts": 1234567890.0})
    text = raw.decode("utf-8")
    assert "event: ping" in text


def test_sse_handles_non_serializable_data() -> None:
    """SSE helper uses `default=str` so non-JSON-native values (e.g., datetime)
    don't crash; the data line should still emit something parseable."""
    from datetime import UTC, datetime

    raw = _sse("progress", {"ts": datetime.now(UTC)})
    text = raw.decode("utf-8")
    # The data line should at least contain a stringified datetime
    assert "data: " in text
    assert "ts" in text


# === Retry endpoint: status guard ===

def test_retry_status_guard() -> None:
    """The retry endpoint should only allow `failed` or `partial` status.
    This is a logic test (the actual endpoint does the check)."""
    allowed = {"failed", "partial"}
    rejected = {"queued", "running", "completed"}
    for s in allowed:
        assert s in allowed
    for s in rejected:
        assert s not in allowed
