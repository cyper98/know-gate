"""Unit tests for the sync progress pub/sub helpers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.sources.progress import progress_channel, publish_event


def test_progress_channel_namespacing() -> None:
    assert progress_channel("job-1") == "kg:sync:job-1:progress"
    assert progress_channel("abc-def") == "kg:sync:abc-def:progress"


@pytest.mark.asyncio
async def test_publish_event_serializes_to_json() -> None:
    """The published payload must be valid JSON with all expected fields."""
    fake_client = MagicMock()
    fake_client.publish = AsyncMock()

    with patch("app.sources.progress.get_redis_client", return_value=fake_client):
        await publish_event(
            "job-42",
            stage="fetch",
            current=3,
            total=10,
            failed=1,
            message="fetched doc-3",
            doc_id="doc-3",
        )

    fake_client.publish.assert_awaited_once()
    args = fake_client.publish.await_args.args
    assert args[0] == "kg:sync:job-42:progress"
    # Second arg is the JSON payload
    payload = json.loads(args[1])
    assert payload["stage"] == "fetch"
    assert payload["current"] == 3
    assert payload["total"] == 10
    assert payload["failed"] == 1
    assert payload["message"] == "fetched doc-3"
    assert payload["doc_id"] == "doc-3"
    assert "ts" in payload


@pytest.mark.asyncio
async def test_publish_event_omits_doc_id_when_none() -> None:
    """If `doc_id` is None, the field should not appear in the payload."""
    fake_client = MagicMock()
    fake_client.publish = AsyncMock()

    with patch("app.sources.progress.get_redis_client", return_value=fake_client):
        await publish_event(
            "job-x", stage="complete", current=10, total=10, failed=0, message="done"
        )

    payload = json.loads(fake_client.publish.await_args.args[1])
    assert "doc_id" not in payload


@pytest.mark.asyncio
async def test_publish_event_swallows_redis_error() -> None:
    """A Redis publish failure must NOT raise (best-effort logging)."""
    fake_client = MagicMock()
    fake_client.publish = AsyncMock(side_effect=RuntimeError("redis down"))

    with patch("app.sources.progress.get_redis_client", return_value=fake_client):
        # MUST NOT raise
        await publish_event("job-y", stage="failed", message="boom")
