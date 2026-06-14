"""Documents API (5 routes).

- GET    /documents                  — list (filter + paginate, scoped to caller's groups)
- GET    /documents/{id}             — detail (caller must have view access)
- PATCH  /documents/{id}             — update metadata (editor)
- DELETE /documents/{id}             — soft-delete (admin)
- GET    /documents/{id}/preview     — pre-signed MinIO URL (caller must have view access)

Permission filtering is done at TWO layers:
  1. List endpoint filters by `user.groups` (no need to materialize the join)
  2. Detail endpoints do a check that the user has at least one group in common
     with the document's access groups. Admins bypass the check.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from fastapi import Query as QueryParam
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.errors import api_error
from app.api.pagination import PageParams, decode_cursor, encode_cursor
from app.api.responses import ErrorCode, Meta, Page
from app.api.v1._permissions import (
    has_admin_role,
    user_group_ids,
    user_has_doc_access,
)
from app.auth.permissions import (
    CurrentUser,
    Permission,
    require_permission,
)
from app.db.enums import DocumentStatus
from app.db.models import Document
from app.db.session import get_session_factory
from app.logging import get_logger
from app.storage.uploader import get_presigned_url

logger = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


# === Schemas ===

class DocumentResponse(BaseModel):
    """Public document view (no internal IDs beyond the document ID itself)."""

    id: str
    source: str
    source_id: str
    source_url: str | None
    source_modified_at: datetime | None
    title: str
    owner: str | None
    document_type: str | None
    mime_type: str | None
    size_bytes: int | None
    language: str | None
    status: str
    indexed_at: datetime | None
    error_message: str | None
    access_groups: list[str] = Field(
        default_factory=list,
        description="Access group IDs this document is shared with.",
    )
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    """Metadata update (title, owner, status). Editor + admin only."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    owner: str | None = Field(default=None, max_length=255)
    status: DocumentStatus | None = None
    access_group_ids: list[str] | None = Field(
        default=None,
        description="Replace the access-group set (admin only; editor may not re-share).",
    )


class DocumentPreviewResponse(BaseModel):
    url: str
    expires_at: datetime


# === Endpoints ===

@router.get("", response_model=Page[DocumentResponse])
async def list_documents(
    user: CurrentUser,
    params: PageParams = Depends(),
    status_filter: DocumentStatus | None = QueryParam(default=None, alias="status"),
    source: str | None = QueryParam(default=None, max_length=32),
    owner: str | None = QueryParam(default=None, max_length=255),
    language: str | None = QueryParam(default=None, max_length=8),
    title_contains: str | None = QueryParam(default=None, max_length=200),
) -> Page[DocumentResponse]:
    """List documents, newest first, scoped to caller's access groups (admins see all)."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Document).options(selectinload(Document.access_groups)).order_by(
            Document.created_at.desc(), Document.id.desc()
        )

        # Permission filter (admins bypass)
        if not has_admin_role(user):
            group_ids = await user_group_ids(session, user["id"])
            if not group_ids:
                # No groups at all → no docs visible
                return Page(data=[], meta=Meta(limit=params.limit))
            stmt = stmt.join(Document.access_groups).where(
                Document.access_groups.property.mapper.class_.id.in_(group_ids)
            )

        # Default: hide soft-deleted docs. Callers can opt-in with `?status=deleted`.
        if status_filter:
            stmt = stmt.where(Document.status == status_filter.value)
        else:
            stmt = stmt.where(Document.status != DocumentStatus.DELETED.value)
        if source:
            stmt = stmt.where(Document.source == source)
        if owner:
            stmt = stmt.where(Document.owner == owner)
        if language:
            stmt = stmt.where(Document.language == language)
        if title_contains:
            stmt = stmt.where(Document.title.ilike(f"%{title_contains}%"))

        # Cursor: limit+1 to detect "more available" without a count(*)
        if params.cursor:
            try:
                cursor_ts, cursor_id = decode_cursor(params.cursor)
            except ValueError:
                raise api_error(400, ErrorCode.BAD_REQUEST, "Invalid cursor") from None
            stmt = stmt.where(
                (Document.created_at < cursor_ts)
                | ((Document.created_at == cursor_ts) & (Document.id < cursor_id))
            )

        stmt = stmt.limit(params.limit + 1)
        rows = (await session.execute(stmt)).scalars().unique().all()
        has_more = len(rows) > params.limit
        rows = rows[: params.limit]

        next_cursor = None
        if has_more and rows:
            next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)

    return Page(
        data=[_doc_to_response(d) for d in rows],
        meta=Meta(limit=params.limit, next_cursor=next_cursor),
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, user: CurrentUser) -> DocumentResponse:
    factory = get_session_factory()
    async with factory() as session:
        doc = await _load_doc_with_groups(session, doc_id)
        if doc is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Document not found")
        if not has_admin_role(user):
            gids = await user_group_ids(session, user["id"])
            if not user_has_doc_access(gids, doc):
                raise api_error(403, ErrorCode.FORBIDDEN, "You don't have access to this document")
    return _doc_to_response(doc)


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    doc_id: str,
    body: DocumentUpdate,
    user: dict = Depends(require_permission(Permission.EDIT_DOC_METADATA)),
) -> DocumentResponse:
    factory = get_session_factory()
    async with factory() as session:
        doc = await _load_doc_with_groups(session, doc_id)
        if doc is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Document not found")

        # Editors may not re-share documents (admin only)
        if body.access_group_ids is not None and not has_admin_role(user):
            raise api_error(
                403,
                ErrorCode.FORBIDDEN,
                "Only admins can change access groups",
            )

        if body.title is not None:
            doc.title = body.title
        if body.owner is not None:
            doc.owner = body.owner
        if body.status is not None:
            doc.status = body.status.value

        if body.access_group_ids is not None:
            from app.db.models import AccessGroup

            groups = (
                await session.execute(
                    select(AccessGroup).where(AccessGroup.id.in_(body.access_group_ids))
                )
            ).scalars().all()
            # Replace the access group set; the association table has an
            # onupdate trigger that bumps `updated_at` automatically.
            doc.access_groups = list(groups)

        await session.commit()
        await session.refresh(doc)

    return _doc_to_response(doc)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    user: dict = Depends(require_permission(Permission.DELETE_DOC)),
) -> None:
    """Soft-delete: set status to `deleted` (retains history for retention window)."""
    factory = get_session_factory()
    async with factory() as session:
        doc = (
            await session.execute(select(Document).where(Document.id == doc_id))
        ).scalar_one_or_none()
        if doc is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Document not found")
        doc.status = DocumentStatus.DELETED.value
        await session.commit()


@router.get("/{doc_id}/preview", response_model=DocumentPreviewResponse)
async def get_document_preview(
    doc_id: str,
    user: CurrentUser,
    expires_seconds: int = QueryParam(default=3600, ge=60, le=86400),
) -> DocumentPreviewResponse:
    """Return a short-lived pre-signed URL for the original file (1h by default)."""
    factory = get_session_factory()
    async with factory() as session:
        doc = await _load_doc_with_groups(session, doc_id)
        if doc is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Document not found")
        if not has_admin_role(user):
            gids = await user_group_ids(session, user["id"])
            if not user_has_doc_access(gids, doc):
                raise api_error(403, ErrorCode.FORBIDDEN, "You don't have access to this document")

    # Object key is `source/source_id` per ingest convention
    object_key = f"{doc.source}/{doc.source_id}"
    url = await get_presigned_url(object_key, expires_seconds=expires_seconds)

    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=expires_seconds)
    return DocumentPreviewResponse(url=url, expires_at=expires_at)


# === Helpers ===

async def _load_doc_with_groups(session: Any, doc_id: str) -> Document | None:
    """Load a document with `access_groups` eagerly loaded."""
    result = await session.execute(
        select(Document)
        .options(selectinload(Document.access_groups))
        .where(Document.id == doc_id)
    )
    return result.scalar_one_or_none()


def _doc_to_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        source=doc.source,
        source_id=doc.source_id,
        source_url=doc.source_url,
        source_modified_at=doc.source_modified_at,
        title=doc.title,
        owner=doc.owner,
        document_type=doc.document_type,
        mime_type=doc.mime_type,
        size_bytes=doc.size_bytes,
        language=doc.language,
        status=doc.status,
        indexed_at=doc.indexed_at,
        error_message=doc.error_message,
        access_groups=[g.id for g in doc.access_groups],
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


__all__ = ["router"]
