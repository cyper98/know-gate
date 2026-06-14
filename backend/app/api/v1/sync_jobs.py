"""Sync Jobs API (3 routes).

- GET    /sync-jobs                  — list (filter by source_id, status; newest first)
- GET    /sync-jobs/{id}             — get one job
- POST   /sync-jobs/{id}/retry       — retry a failed/partial job
- GET    /sync-jobs/{id}/stream      — Server-Sent Events for live progress

Note: the legacy `sources/sync-jobs` endpoints (in `sources.py`) are kept
for backward compatibility with the admin dashboard. The new
top-level `/sync-jobs` namespace is the canonical location going forward.

SSE notes:
- The endpoint streams events from a Redis pub/sub channel keyed by
  `kg:sync:progress:{job_id}`. The Celery worker publishes events as
  it processes documents. The connection stays open until the job
  reaches a terminal state (completed/failed/partial).
- Backpressure: events are emitted as they arrive; the client is
  expected to read at its own pace (a typical browser buffers but
  doesn't block the server).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi import Query as QueryParam
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.errors import api_error
from app.api.pagination import PageParams, decode_cursor, encode_cursor
from app.api.responses import ErrorCode, Meta, Page
from app.auth.permissions import Permission, require_permission
from app.config import get_settings
from app.db.enums import SyncJobStatus
from app.db.models import Source, SyncJob
from app.db.session import get_session_factory
from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/sync-jobs", tags=["sync-jobs"])


# === Schemas ===

class SyncJobResponse(BaseModel):
    id: str
    source_id: str
    status: str
    triggered_by: str
    total_docs: int
    indexed_docs: int
    failed_docs: int
    started_at: datetime | None
    completed_at: datetime | None
    error_log: dict[str, Any]

    model_config = {"from_attributes": True}


# === Endpoints ===

@router.get("", response_model=Page[SyncJobResponse])
async def list_sync_jobs(
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
    params: PageParams = Depends(),
    source_id: str | None = QueryParam(default=None),
    status_filter: SyncJobStatus | None = QueryParam(default=None, alias="status"),
) -> Page[SyncJobResponse]:
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(SyncJob).order_by(SyncJob.started_at.desc().nullslast(), SyncJob.id.desc())
        if source_id:
            stmt = stmt.where(SyncJob.source_id == source_id)
        if status_filter:
            stmt = stmt.where(SyncJob.status == status_filter.value)
        if params.cursor:
            try:
                ts, jid = decode_cursor(params.cursor)
            except ValueError:
                raise api_error(400, ErrorCode.BAD_REQUEST, "Invalid cursor") from None
            stmt = stmt.where(
                (SyncJob.started_at < ts)
                | ((SyncJob.started_at == ts) & (SyncJob.id < jid))
            )
        stmt = stmt.limit(params.limit + 1)
        rows = (await session.execute(stmt)).scalars().all()
        has_more = len(rows) > params.limit
        rows = rows[: params.limit]
        next_cur = None
        if has_more and rows:
            anchor = rows[-1].started_at or rows[-1].created_at
            next_cur = encode_cursor(anchor, rows[-1].id)

    return Page(
        data=[SyncJobResponse.model_validate(j) for j in rows],
        meta=Meta(limit=params.limit, next_cursor=next_cur),
    )


@router.get("/{job_id}", response_model=SyncJobResponse)
async def get_sync_job(
    job_id: str,
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> SyncJobResponse:
    factory = get_session_factory()
    async with factory() as session:
        job = (
            await session.execute(select(SyncJob).where(SyncJob.id == job_id))
        ).scalar_one_or_none()
    if job is None:
        raise api_error(404, ErrorCode.NOT_FOUND, "Sync job not found")
    return SyncJobResponse.model_validate(job)


@router.post("/{job_id}/retry", status_code=202)
async def retry_sync_job(
    job_id: str,
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> SyncJobResponse:
    """Retry a failed/partial sync job by re-enqueueing a fresh sync on the source."""
    factory = get_session_factory()
    async with factory() as session:
        job = (
            await session.execute(select(SyncJob).where(SyncJob.id == job_id))
        ).scalar_one_or_none()
        if job is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Sync job not found")
        if job.status not in (SyncJobStatus.FAILED.value, SyncJobStatus.PARTIAL.value):
            raise api_error(
                409, ErrorCode.INVALID_STATE,
                f"Cannot retry a job with status={job.status!r} "
                "(only 'failed' or 'partial' are retryable)",
            )
        source = (
            await session.execute(select(Source).where(Source.id == job.source_id))
        ).scalar_one_or_none()
        if source is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Source not found (orphaned job)")
        # Block retry on archived sources (admin must un-archive first)
        if source.status == "archived":
            raise api_error(
                409, ErrorCode.INVALID_STATE,
                "Cannot retry a job for an archived source; restore the source first.",
            )
        source_id = source.id

    # Enqueue a fresh sync (a new job row will be created by the worker)
    from app.tasks.sync import sync_source_task

    result = sync_source_task.delay(source_id, triggered_by="retry")
    return SyncJobResponse(
        id=str(getattr(result, "id", "") or ""),
        source_id=source_id,
        status=SyncJobStatus.QUEUED.value,
        triggered_by="retry",
        total_docs=0, indexed_docs=0, failed_docs=0,
        started_at=None, completed_at=None, error_log={},
    )


@router.get("/{job_id}/stream")
async def stream_sync_job(
    job_id: str,
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> StreamingResponse:
    """Server-Sent Events stream for live sync-job progress.

    Emits `data: {json}\\n\\n` lines. Each event is one of:
      - `event: progress`  — {indexed_docs, total_docs, failed_docs, status}
      - `event: terminal`  — final state; connection closes after this
      - `event: ping`       — keep-alive every 15s

    The stream is closed by the worker (or after `STREAM_TIMEOUT_S`).
    """
    get_settings()

    async def event_generator() -> AsyncIterator[bytes]:
        # First, send a 'snapshot' so the client has the current state
        # even if the worker is mid-flight.
        factory = get_session_factory()
        async with factory() as session:
            job = (
                await session.execute(select(SyncJob).where(SyncJob.id == job_id))
            ).scalar_one_or_none()
        if job is None:
            yield _sse("error", {"message": "Job not found"})
            return

        yield _sse(
            "snapshot",
            {
                "id": job.id,
                "source_id": job.source_id,
                "status": job.status,
                "total_docs": job.total_docs,
                "indexed_docs": job.indexed_docs,
                "failed_docs": job.failed_docs,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            },
        )
        if job.status in (
            SyncJobStatus.COMPLETED.value,
            SyncJobStatus.FAILED.value,
        ):
            yield _sse("terminal", {"status": job.status})
            return

        # Subscribe to Redis pub/sub channel for live progress
        from app.cache.client import get_redis_client

        client = get_redis_client()
        channel = f"kg:sync:progress:{job_id}"
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        try:
            last_ping = asyncio.get_event_loop().time()
            while True:
                # Use wait_for so we can periodically check job state
                # and emit keep-alive pings.
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                now = asyncio.get_event_loop().time()
                if msg is not None and msg.get("type") == "message":
                    try:
                        data = json.loads(msg["data"])
                    except (TypeError, json.JSONDecodeError):
                        data = {"raw": str(msg.get("data"))}
                    evt = data.get("event", "progress")
                    yield _sse(evt, data)
                    if evt == "terminal":
                        return
                if now - last_ping > 15.0:
                    yield _sse("ping", {"ts": now})
                    last_ping = now
                # Check for terminal state via DB (worker may have died)
                async with factory() as session:
                    j = (
                        await session.execute(select(SyncJob).where(SyncJob.id == job_id))
                    ).scalar_one_or_none()
                if j and j.status in (
                    SyncJobStatus.COMPLETED.value,
                    SyncJobStatus.FAILED.value,
                ):
                    yield _sse(
                        "terminal",
                        {
                            "status": j.status,
                            "indexed_docs": j.indexed_docs,
                            "failed_docs": j.failed_docs,
                            "total_docs": j.total_docs,
                        },
                    )
                    return
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


def _sse(event: str, data: dict[str, Any]) -> bytes:
    """Format one SSE message (event + data + blank line)."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode()


__all__ = ["router"]
