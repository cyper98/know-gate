"""Celery task entrypoints for sync operations.

The Celery worker is sync; the sync engine + DB layer are async. We bridge
by using `asyncio.run` inside the task body. This is OK because:
- Each task is one event loop
- DB sessions are per-task (no sharing across tasks)
- Workers process one task at a time (prefetch_multiplier=1)

Each `_create_job` / `_finalize_crashed_job` / `_list_active_source_ids` helper
opens its own event loop via `asyncio.run` because they also touch the async
DB layer. The actual sync engine is run via `asyncio.run(run_sync(...))`
inside the task body.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.enums import SyncJobStatus
from app.db.models import Source, SyncJob
from app.db.session import get_session_factory
from app.logging import get_logger
from app.sources.sync import run_sync

logger = get_logger(__name__)


# === Tasks ===

@celery_app.task(name="sync_source", bind=True, max_retries=3, default_retry_delay=30)
def sync_source_task(self, source_id: str, triggered_by: str = "manual") -> str:
    """Run a full sync for one Source. Returns the created SyncJob ID.

    Retries: 3 with 30s delay on transient failures. Auth errors are NOT
    retried (they need admin intervention).
    """
    job_id = asyncio.run(_create_job(source_id, triggered_by))
    try:
        asyncio.run(run_sync(source_id=source_id, job_id=job_id, triggered_by=triggered_by))
    except Exception as e:
        logger.exception("sync_task_crashed", source_id=source_id, job_id=job_id)
        # Don't retry auth errors
        if "auth" in str(e).lower():
            return job_id
        try:
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            asyncio.run(_finalize_crashed_job(job_id, str(e)))
    return job_id


@celery_app.task(name="sync_all_sources")
def sync_all_sources_task() -> list[str]:
    """Enqueue a sync task for every ACTIVE source. Returns the list of job IDs.

    Scheduled by Celery Beat every 5 min (see `beat_schedule.py`).
    """
    source_ids = asyncio.run(_list_active_source_ids())

    job_ids: list[str] = []
    for sid in source_ids:
        jid = sync_source_task.delay(sid, triggered_by="scheduled")
        job_ids.append(str(jid))
    logger.info("sync_all_sources_enqueued", count=len(job_ids))
    return job_ids


# === Sync job lifecycle helpers (async, run via asyncio.run from sync tasks) ===

async def _create_job(source_id: str, triggered_by: str) -> str:
    """Insert a QUEUED SyncJob row. Returns the job ID."""
    job_id = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        job = SyncJob(
            id=job_id,
            source_id=source_id,
            status=SyncJobStatus.QUEUED.value,
            triggered_by=triggered_by,
            started_at=datetime.now(UTC),
        )
        session.add(job)
        await session.commit()
    return job_id


async def _finalize_crashed_job(job_id: str, error: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(SyncJob).where(SyncJob.id == job_id))
        job = result.scalar_one()
        job.status = SyncJobStatus.FAILED.value
        existing = dict(job.error_log or {})
        existing["_summary"] = f"crashed: {error[:500]}"
        job.error_log = existing
        job.completed_at = datetime.now(UTC)
        await session.commit()


async def _list_active_source_ids() -> list[str]:
    """Return IDs of all sources with status='active'."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Source.id).where(Source.status == "active")
        )
        return [str(row[0]) for row in result.all()]
