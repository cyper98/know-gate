"""Sync progress events (Redis pub/sub, used by sync engine → API → SSE).

The sync engine publishes a JSON event after every doc processed. The API
endpoint for SSE subscribes and forwards events to the browser.

Channel naming: `kg:sync:{job_id}` (one channel per sync job).
Backpressure: events older than `progress_ttl_seconds` are dropped by the
worker (no replay; SSE is a live stream).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.cache.client import get_redis_client
from app.logging import get_logger

logger = get_logger(__name__)

# Channel name (matches the SSE subscription pattern in the API layer)
def progress_channel(job_id: str) -> str:
    """Redis pub/sub channel for one sync job's progress events."""
    return f"kg:sync:{job_id}:progress"


# === Event schema (kept stable; consumed by the SSE endpoint) ===

# An event is a JSON dict:
# {
#   "ts": "2026-06-14T10:42:00Z",
#   "stage": "fetch" | "upload" | "index" | "complete" | "failed",
#   "current": 12,
#   "total": 100,
#   "failed": 1,
#   "message": "fetched doc-abc (5.2 MB)",
#   "doc_id": "abc123",  # optional
# }


async def publish_event(
    job_id: str,
    *,
    stage: str,
    current: int = 0,
    total: int = 0,
    failed: int = 0,
    message: str = "",
    doc_id: str | None = None,
) -> None:
    """Publish one progress event to the job's pub/sub channel.

    Best-effort: a Redis outage is logged but does not break the sync
    (the work continues; the SSE stream just won't see this event).
    """
    event: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "stage": stage,
        "current": current,
        "total": total,
        "failed": failed,
        "message": message,
    }
    if doc_id is not None:
        event["doc_id"] = doc_id

    try:
        client = get_redis_client()
        await client.publish(progress_channel(job_id), json.dumps(event))
    except Exception:
        # Don't break the sync over a publish failure
        logger.exception("sync_progress_publish_failed", job_id=job_id, stage=stage)


async def subscribe_events(job_id: str) -> AsyncIterator[dict[str, Any]]:
    """Async iterator over progress events for one sync job.

    Yields parsed event dicts. The caller (SSE endpoint) wraps each in the
    `data: <json>\n\n` SSE frame format.

    This is a generator that returns when the caller stops iterating (client
    disconnect) or when Redis closes the pubsub.
    """
    client = get_redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(progress_channel(job_id))
    try:
        async for raw in pubsub.listen():
            if raw is None or raw.get("type") != "message":
                continue
            data = raw.get("data")
            if data is None:
                continue
            try:
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode("utf-8")
                yield json.loads(data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("sync_progress_bad_event", job_id=job_id, raw=data)
    finally:
        await pubsub.unsubscribe(progress_channel(job_id))
        await pubsub.aclose()


__all__ = ["progress_channel", "publish_event", "subscribe_events"]
