"""System Settings + Audit Log API (3 routes).

- GET    /settings            — read singleton settings (admin)
- PATCH  /settings            — update settings (admin)
- GET    /settings/audit-log  — read audit log (admin, paginated, newest first)

The `SystemSettings` row is a singleton (one row in `system_settings`).
We upsert on first read so the API never 404s.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi import Query as QueryParam
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import api_error
from app.api.pagination import PageParams, decode_cursor, encode_cursor
from app.api.responses import ErrorCode, Meta, Page
from app.audit.log import log_event
from app.auth.permissions import Permission, require_permission
from app.db.models import AuditLog, SystemSettings
from app.db.session import get_session_factory
from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


# === Schemas ===

class SettingsResponse(BaseModel):
    id: str
    default_language: str
    default_query_language: str
    feedback_retention_days: int
    audit_retention_days: int
    rate_limit_query_per_minute: int
    max_doc_size_mb: int
    allow_signup: bool
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    default_language: str | None = Field(default=None, min_length=2, max_length=8)
    default_query_language: str | None = Field(default=None, min_length=2, max_length=8)
    feedback_retention_days: int | None = Field(default=None, ge=1, le=3650)
    audit_retention_days: int | None = Field(default=None, ge=1, le=3650)
    rate_limit_query_per_minute: int | None = Field(default=None, ge=1, le=10000)
    max_doc_size_mb: int | None = Field(default=None, ge=1, le=1024)
    allow_signup: bool | None = None


class AuditLogEntry(BaseModel):
    id: str
    actor_id: str | None
    actor_email: str | None
    action: str
    target_type: str
    target_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip_address: str | None
    detail: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# === Helpers ===

async def _load_singleton_settings(session: Any) -> SystemSettings:
    """Get the (only) SystemSettings row, creating a default one on first access."""
    row = (await session.execute(select(SystemSettings))).scalars().first()
    if row is None:
        row = SystemSettings()
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


# === Endpoints ===

@router.get("", response_model=SettingsResponse)
async def get_settings(
    _user: dict = Depends(require_permission(Permission.MANAGE_SETTINGS)),
) -> SettingsResponse:
    factory = get_session_factory()
    async with factory() as session:
        s = await _load_singleton_settings(session)
    return SettingsResponse.model_validate(s)


@router.patch("", response_model=SettingsResponse)
async def update_settings(
    body: SettingsUpdate,
    actor: dict = Depends(require_permission(Permission.MANAGE_SETTINGS)),
) -> SettingsResponse:
    factory = get_session_factory()
    async with factory() as session:
        s = await _load_singleton_settings(session)
        before = {
            "default_language": s.default_language,
            "default_query_language": s.default_query_language,
            "feedback_retention_days": s.feedback_retention_days,
            "audit_retention_days": s.audit_retention_days,
            "rate_limit_query_per_minute": s.rate_limit_query_per_minute,
            "max_doc_size_mb": s.max_doc_size_mb,
            "allow_signup": s.allow_signup,
        }
        if body.default_language is not None:
            s.default_language = body.default_language
        if body.default_query_language is not None:
            s.default_query_language = body.default_query_language
        if body.feedback_retention_days is not None:
            s.feedback_retention_days = body.feedback_retention_days
        if body.audit_retention_days is not None:
            s.audit_retention_days = body.audit_retention_days
        if body.rate_limit_query_per_minute is not None:
            s.rate_limit_query_per_minute = body.rate_limit_query_per_minute
        if body.max_doc_size_mb is not None:
            s.max_doc_size_mb = body.max_doc_size_mb
        if body.allow_signup is not None:
            s.allow_signup = body.allow_signup
        await session.commit()
        await session.refresh(s)
        after = {
            "default_language": s.default_language,
            "default_query_language": s.default_query_language,
            "feedback_retention_days": s.feedback_retention_days,
            "audit_retention_days": s.audit_retention_days,
            "rate_limit_query_per_minute": s.rate_limit_query_per_minute,
            "max_doc_size_mb": s.max_doc_size_mb,
            "allow_signup": s.allow_signup,
        }

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="settings.update",
            target_type="settings", target_id=s.id, before=before, after=after,
        )
    )
    return SettingsResponse.model_validate(s)


@router.get("/audit-log", response_model=Page[AuditLogEntry])
async def get_audit_log(
    _user: dict = Depends(require_permission(Permission.VIEW_AUDIT_LOG)),
    params: PageParams = Depends(),
    action: str | None = QueryParam(default=None, max_length=64),
    target_type: str | None = QueryParam(default=None, max_length=32),
    actor_id: str | None = QueryParam(default=None, max_length=36),
) -> Page[AuditLogEntry]:
    """List audit log entries (newest first). Admins only."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if target_type:
            stmt = stmt.where(AuditLog.target_type == target_type)
        if actor_id:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if params.cursor:
            try:
                ts, aid = decode_cursor(params.cursor)
            except ValueError:
                raise api_error(400, ErrorCode.BAD_REQUEST, "Invalid cursor") from None
            stmt = stmt.where(
                (AuditLog.created_at < ts) | ((AuditLog.created_at == ts) & (AuditLog.id < aid))
            )
        stmt = stmt.limit(params.limit + 1)
        rows = (await session.execute(stmt)).scalars().all()
        has_more = len(rows) > params.limit
        rows = rows[: params.limit]
        next_cur = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None

    return Page(
        data=[AuditLogEntry.model_validate(r) for r in rows],
        meta=Meta(limit=params.limit, next_cursor=next_cur),
    )


__all__ = ["router"]
