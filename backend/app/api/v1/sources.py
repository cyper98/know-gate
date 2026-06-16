"""Source management API (admin only).

Endpoints:
- GET    /sources                  — list
- POST   /sources                  — create
- GET    /sources/{id}             — read
- PATCH  /sources/{id}             — update (name, status)
- DELETE /sources/{id}             — archive (soft delete)
- POST   /sources/{id}/sync        — manual trigger (enqueues Celery task)
- GET    /sources/sync-jobs        — list jobs
- GET    /sources/sync-jobs/{id}   — read job

All endpoints require the caller to be an admin (permission check).
The actual `Source.config_encrypted` is never returned to the client (only
metadata: type, name, status, last_sync_at).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.permissions import Permission, require_permission
from app.config import get_settings
from app.crypto.aes import encrypt_str
from app.db.enums import SourceStatus, SourceType
from app.db.models import Source, SyncJob
from app.db.session import get_session_factory

from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/sources", tags=["sources"])


# === Schemas ===

class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: SourceType
    # For Google Drive: a dict containing the OAuth flow result
    # For Notion: a dict containing the integration token
    config: dict[str, Any]


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: SourceStatus | None = None


class SourceResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    last_sync_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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

@router.get("", response_model=list[SourceResponse])
async def list_sources(
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> list[SourceResponse]:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Source).order_by(Source.created_at.desc()))
        sources = result.scalars().all()
    return [SourceResponse.model_validate(s) for s in sources]


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceCreate,
    user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> SourceResponse:
    settings = get_settings()
    key = settings.kg_encryption_key.get_secret_value()
    factory = get_session_factory()
    async with factory() as session:
        # Encrypt the connector config (the connector-specific dict)
        config_json = _serialize_config(body.type, body.config)
        encrypted = encrypt_str(config_json, key)
        src = Source(
            id=str(uuid.uuid4()),
            name=body.name,
            type=body.type.value,
            config_encrypted=encrypted,
            status=SourceStatus.ACTIVE.value,
            created_by=user["id"],
        )
        session.add(src)
        await session.commit()
        await session.refresh(src)
    return SourceResponse.model_validate(src)


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: str,
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> SourceResponse:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        src = result.scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return SourceResponse.model_validate(src)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: str,
    body: SourceUpdate,
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> SourceResponse:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        src = result.scalar_one_or_none()
        if src is None:
            raise HTTPException(status_code=404, detail="Source not found")
        if body.name is not None:
            src.name = body.name
        if body.status is not None:
            src.status = body.status.value
        await session.commit()
        await session.refresh(src)
    return SourceResponse.model_validate(src)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_source(
    source_id: str,
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
):
    """Archive a source (soft delete — keeps history)."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        src = result.scalar_one_or_none()
        if src is None:
            raise HTTPException(status_code=404, detail="Source not found")
        src.status = SourceStatus.ARCHIVED.value
        await session.commit()


@router.post("/{source_id}/sync", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    source_id: str,
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> SyncJobResponse:
    """Enqueue a manual sync. Returns the (newly created) SyncJob row.

    Rate limit: at most one manual trigger per source per 30 seconds. This
    prevents runaway clients from triggering hundreds of overlapping jobs
    on a single source (which would compete for the same connector's
    rate-limited API and potentially trigger Drive's hard 429 ban).
    """
    from datetime import datetime, timedelta

    from app.tasks.sync import sync_source_task

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        src = result.scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if src.status not in (SourceStatus.ACTIVE.value, SourceStatus.AUTH_FAILED.value):
        raise HTTPException(
            status_code=409,
            detail=f"Source status is {src.status}; cannot sync (must be active or auth_failed)",
        )

    # Cooldown: reject if a sync ran in the last 30 seconds
    if src.last_sync_at is not None:
        elapsed = datetime.now(UTC) - src.last_sync_at
        if elapsed < timedelta(seconds=30):
            retry_after = int((timedelta(seconds=30) - elapsed).total_seconds())
            raise HTTPException(
                status_code=429,
                detail=f"Source synced {int(elapsed.total_seconds())}s ago; "
                       f"wait {retry_after}s before triggering again",
                headers={"Retry-After": str(retry_after)},
            )

    # Enqueue
    async_result = sync_source_task.delay(source_id, triggered_by="manual")
    return SyncJobResponse(
        id=str(getattr(async_result, "id", "") or ""),
        source_id=source_id,
        status="queued",
        triggered_by="manual",
        total_docs=0,
        indexed_docs=0,
        failed_docs=0,
        started_at=None,
        completed_at=None,
        error_log={},
    )


@router.get("/sync-jobs", response_model=list[SyncJobResponse])
async def list_sync_jobs(
    source_id: str | None = None,
    limit: int = 50,
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> list[SyncJobResponse]:
    """List sync jobs, most recent first. Optional filter by source_id."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(SyncJob).order_by(SyncJob.started_at.desc().nullslast()).limit(limit)
        if source_id:
            stmt = stmt.where(SyncJob.source_id == source_id)
        result = await session.execute(stmt)
        jobs = result.scalars().all()
    return [SyncJobResponse.model_validate(j) for j in jobs]


@router.get("/sync-jobs/{job_id}", response_model=SyncJobResponse)
async def get_sync_job(
    job_id: str,
    _user: dict = Depends(require_permission(Permission.MANAGE_SOURCES)),
) -> SyncJobResponse:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(SyncJob).where(SyncJob.id == job_id))
        job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Sync job not found")
    return SyncJobResponse.model_validate(job)


# === Helpers ===

def _serialize_config(source_type: SourceType, cfg: dict[str, Any]) -> str:
    """Serialize the per-type config dict to a JSON string (then encrypted)."""
    import json

    return json.dumps(cfg, separators=(",", ":"))
