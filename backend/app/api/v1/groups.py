"""Access Groups API.

- GET    /groups                          — list
- POST   /groups                          — create
- PATCH  /groups/{id}                     — update name/description
- DELETE /groups/{id}                     — delete (blocked if any user or document is mapped)
- POST   /groups/{id}/users               — add user to group
- DELETE /groups/{id}/users/{userId}      — remove user from group
- POST   /groups/{id}/documents           — add document to group (share)
- DELETE /groups/{id}/documents/{docId}   — unshare document from group

Access groups are the data-level filter that complements RBAC.
A user can only see documents whose `access_groups` intersect the user's
own group set (enforced in `app.api.v1.documents` and the retrieval pipeline).

All endpoints require admin (MANAGE_GROUPS permission).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.errors import api_error
from app.api.pagination import PageParams, decode_cursor, encode_cursor
from app.api.responses import ErrorCode, Meta, Page
from app.audit.log import log_event
from app.auth.permissions import Permission, require_permission
from app.db.models import (
    AccessGroup,
    Document,
    DocumentGroup,
    User,
    UserGroup,
)
from app.db.session import get_session_factory
from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/groups", tags=["groups"])


# === Schemas ===

class GroupResponse(BaseModel):
    id: str
    name: str
    description: str | None
    user_count: int = 0
    document_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=500)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=500)


class GroupMemberRequest(BaseModel):
    user_id: str


class GroupDocumentRequest(BaseModel):
    document_id: str


# === Endpoints ===

@router.get("", response_model=Page[GroupResponse])
async def list_groups(
    _user: dict = Depends(require_permission(Permission.MANAGE_GROUPS)),
    params: PageParams = Depends(),
) -> Page[GroupResponse]:
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(AccessGroup).order_by(AccessGroup.created_at.desc(), AccessGroup.id.desc())
        if params.cursor:
            try:
                ts, gid = decode_cursor(params.cursor)
            except ValueError:
                raise api_error(400, ErrorCode.BAD_REQUEST, "Invalid cursor") from None
            stmt = stmt.where(
                (AccessGroup.created_at < ts) | ((AccessGroup.created_at == ts) & (AccessGroup.id < gid))
            )
        stmt = stmt.limit(params.limit + 1)
        rows = (await session.execute(stmt)).scalars().all()
        has_more = len(rows) > params.limit
        rows = rows[: params.limit]
        next_cur = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None

        ids = [g.id for g in rows]
        user_counts: dict[str, int] = dict.fromkeys(ids, 0)
        doc_counts: dict[str, int] = dict.fromkeys(ids, 0)
        if ids:
            uc = (
                await session.execute(
                    select(UserGroup.group_id, func.count(UserGroup.user_id))
                    .where(UserGroup.group_id.in_(ids))
                    .group_by(UserGroup.group_id)
                )
            ).all()
            for gid, c in uc:
                user_counts[gid] = int(c)
            dc = (
                await session.execute(
                    select(DocumentGroup.group_id, func.count(DocumentGroup.document_id))
                    .where(DocumentGroup.group_id.in_(ids))
                    .group_by(DocumentGroup.group_id)
                )
            ).all()
            for gid, c in dc:
                doc_counts[gid] = int(c)

    return Page(
        data=[
            GroupResponse(
                id=g.id, name=g.name, description=g.description,
                user_count=user_counts.get(g.id, 0), document_count=doc_counts.get(g.id, 0),
                created_at=g.created_at, updated_at=g.updated_at,
            )
            for g in rows
        ],
        meta=Meta(limit=params.limit, next_cursor=next_cur),
    )


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(
    body: GroupCreate,
    actor: dict = Depends(require_permission(Permission.MANAGE_GROUPS)),
) -> GroupResponse:
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(select(AccessGroup).where(AccessGroup.name == body.name))
        ).scalar_one_or_none()
        if existing is not None:
            raise api_error(409, ErrorCode.CONFLICT, f"Group {body.name!r} already exists")

        g = AccessGroup(
            id=str(uuid.uuid4()),
            name=body.name,
            description=body.description,
            created_by=actor["id"],
        )
        session.add(g)
        await session.commit()
        await session.refresh(g)

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="group.create",
            target_type="group", target_id=g.id,
            after={"name": body.name, "description": body.description},
        )
    )
    return GroupResponse(
        id=g.id, name=g.name, description=g.description,
        user_count=0, document_count=0,
        created_at=g.created_at, updated_at=g.updated_at,
    )


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: str,
    body: GroupUpdate,
    actor: dict = Depends(require_permission(Permission.MANAGE_GROUPS)),
) -> GroupResponse:
    factory = get_session_factory()
    async with factory() as session:
        g = (
            await session.execute(select(AccessGroup).where(AccessGroup.id == group_id))
        ).scalar_one_or_none()
        if g is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Group not found")

        before = {"name": g.name, "description": g.description}
        if body.name is not None and body.name != g.name:
            dup = (
                await session.execute(
                    select(AccessGroup).where(AccessGroup.name == body.name, AccessGroup.id != g.id)
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise api_error(409, ErrorCode.CONFLICT, f"Group name {body.name!r} already in use")
            g.name = body.name
        if body.description is not None:
            g.description = body.description
        await session.commit()
        await session.refresh(g)
        uc = (
            await session.execute(
                select(func.count(UserGroup.user_id)).where(UserGroup.group_id == g.id)
            )
        ).scalar_one() or 0
        dc = (
            await session.execute(
                select(func.count(DocumentGroup.document_id)).where(DocumentGroup.group_id == g.id)
            )
        ).scalar_one() or 0

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="group.update",
            target_type="group", target_id=g.id,
            before=before, after={"name": g.name, "description": g.description},
        )
    )
    return GroupResponse(
        id=g.id, name=g.name, description=g.description,
        user_count=int(uc), document_count=int(dc),
        created_at=g.created_at, updated_at=g.updated_at,
    )


@router.delete("/{group_id}", status_code=204, response_class=Response)
async def delete_group(
    group_id: str,
    actor: dict = Depends(require_permission(Permission.MANAGE_GROUPS)),
):
    factory = get_session_factory()
    async with factory() as session:
        g = (
            await session.execute(select(AccessGroup).where(AccessGroup.id == group_id))
        ).scalar_one_or_none()
        if g is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Group not found")

        uc = (
            await session.execute(
                select(func.count(UserGroup.user_id)).where(UserGroup.group_id == g.id)
            )
        ).scalar_one() or 0
        dc = (
            await session.execute(
                select(func.count(DocumentGroup.document_id)).where(DocumentGroup.group_id == g.id)
            )
        ).scalar_one() or 0
        if uc or dc:
            raise api_error(
                409, ErrorCode.CONFLICT,
                f"Group {g.name!r} is in use ({int(uc)} users, {int(dc)} documents); remove all mappings first.",
            )

        await session.delete(g)
        await session.commit()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="group.delete",
            target_type="group", target_id=group_id, before={"name": g.name},
        )
    )


@router.post("/{group_id}/users", status_code=201)
async def add_user_to_group(
    group_id: str,
    body: GroupMemberRequest,
    actor: dict = Depends(require_permission(Permission.MANAGE_GROUPS)),
) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        g = (
            await session.execute(select(AccessGroup).where(AccessGroup.id == group_id))
        ).scalar_one_or_none()
        if g is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Group not found")
        u = (
            await session.execute(select(User).where(User.id == body.user_id))
        ).scalar_one_or_none()
        if u is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "User not found")

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(UserGroup).values(
            user_id=u.id, group_id=g.id, joined_at=datetime.now(UTC)
        ).on_conflict_do_nothing(index_elements=["user_id", "group_id"])
        await session.execute(stmt)
        await session.commit()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="group.user.add",
            target_type="group", target_id=g.id,
            after={"user_id": u.id, "group": g.name},
        )
    )
    return {"group_id": g.id, "user_id": u.id}


@router.delete("/{group_id}/users/{user_id}", status_code=204, response_class=Response)
async def remove_user_from_group(
    group_id: str,
    user_id: str,
    actor: dict = Depends(require_permission(Permission.MANAGE_GROUPS)),
):
    from sqlalchemy import delete as sql_delete

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            sql_delete(UserGroup).where(
                UserGroup.group_id == group_id, UserGroup.user_id == user_id
            )
        )
        await session.commit()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="group.user.remove",
            target_type="group", target_id=group_id, before={"user_id": user_id},
        )
    )


@router.post("/{group_id}/documents", status_code=201)
async def add_document_to_group(
    group_id: str,
    body: GroupDocumentRequest,
    actor: dict = Depends(require_permission(Permission.MANAGE_GROUPS)),
) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        g = (
            await session.execute(select(AccessGroup).where(AccessGroup.id == group_id))
        ).scalar_one_or_none()
        if g is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Group not found")
        d = (
            await session.execute(select(Document).where(Document.id == body.document_id))
        ).scalar_one_or_none()
        if d is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Document not found")

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(DocumentGroup).values(
            document_id=d.id, group_id=g.id
        ).on_conflict_do_nothing(index_elements=["document_id", "group_id"])
        await session.execute(stmt)
        await session.commit()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="group.document.add",
            target_type="group", target_id=g.id,
            after={"document_id": d.id, "group": g.name},
        )
    )
    return {"group_id": g.id, "document_id": d.id}


@router.delete("/{group_id}/documents/{doc_id}", status_code=204, response_class=Response)
async def remove_document_from_group(
    group_id: str,
    doc_id: str,
    actor: dict = Depends(require_permission(Permission.MANAGE_GROUPS)),
):
    from sqlalchemy import delete as sql_delete

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            sql_delete(DocumentGroup).where(
                DocumentGroup.group_id == group_id, DocumentGroup.document_id == doc_id
            )
        )
        await session.commit()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="group.document.remove",
            target_type="group", target_id=group_id, before={"document_id": doc_id},
        )
    )


__all__ = ["router"]
