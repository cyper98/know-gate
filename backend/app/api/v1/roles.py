"""Roles API (4 routes).

- GET    /roles                — list
- POST   /roles                — create (custom role with explicit permission set)
- PATCH  /roles/{id}           — update name/description/permissions
- DELETE /roles/{id}           — delete (blocked if any user holds this role)

The 3 default roles (admin/editor/member) are seeded and may be edited
(their name/description/permissions) but not deleted — DELETE returns
409 if `user_count > 0`. The static `admin` role's permissions should
be the full set; clients may add custom roles for fine-grained access
in larger orgs.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.errors import api_error
from app.api.pagination import PageParams
from app.api.responses import ErrorCode, Meta, Page
from app.audit.log import log_event
from app.auth.permissions import (
    CurrentUser,
    Permission,
    get_role_permissions,
    require_permission,
)
from app.db.models import Role, UserRole
from app.db.session import get_session_factory
from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/roles", tags=["roles"])


# === Schemas ===

class RoleResponse(BaseModel):
    id: str
    name: str
    description: str | None
    permissions: list[str]
    user_count: int = 0
    is_static: bool = Field(
        default=False,
        description="True for the 3 seeded roles (admin/editor/member) — can be edited but name is reserved.",
    )
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(
        default_factory=list,
        description="Permission enum values (see Permission). Empty = no permissions.",
    )


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None


STATIC_ROLE_NAMES = frozenset({"admin", "editor", "member"})


def _validate_permissions(perms: list[str]) -> None:
    """Ensure all permission strings are in the known Permission enum."""
    known = {p.value for p in Permission}
    bad = [p for p in perms if p not in known]
    if bad:
        raise api_error(
            400, ErrorCode.BAD_REQUEST,
            f"Unknown permission(s): {bad}. Allowed: {sorted(known)}",
        )


# === Endpoints ===

@router.get("", response_model=Page[RoleResponse])
async def list_roles(
    _user: CurrentUser,
    params: PageParams = Depends(),
) -> Page[RoleResponse]:
    """List roles (any authenticated user; the role picker is part of the user-detail page)."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Role).order_by(Role.name.asc())
        if params.cursor:
            try:
                # Roles sort by name; cursor encodes (name, id) tuple
                from app.api.pagination import decode_role_cursor

                _name, _id = decode_role_cursor(params.cursor)
                stmt = stmt.where(
                    (Role.name > _name) | ((Role.name == _name) & (Role.id > _id))
                )
            except (ValueError, AttributeError):
                raise api_error(400, ErrorCode.BAD_REQUEST, "Invalid cursor") from None
        stmt = stmt.limit(params.limit + 1)
        rows = (await session.execute(stmt)).scalars().all()
        has_more = len(rows) > params.limit
        rows = rows[: params.limit]
        next_cur = None
        if has_more and rows:
            from app.api.pagination import encode_role_cursor

            next_cur = encode_role_cursor(rows[-1].name, rows[-1].id)

        # User counts (one query)
        ids = [r.id for r in rows]
        counts: dict[str, int] = dict.fromkeys(ids, 0)
        if ids:
            count_rows = (
                await session.execute(
                    select(UserRole.role_id, func.count(UserRole.user_id))
                    .where(UserRole.role_id.in_(ids))
                    .group_by(UserRole.role_id)
                )
            ).all()
            for rid, cnt in count_rows:
                counts[rid] = int(cnt)

    return Page(
        data=[
            RoleResponse(
                id=r.id, name=r.name, description=r.description,
                permissions=r.permissions or [], user_count=counts.get(r.id, 0),
                is_static=r.name in STATIC_ROLE_NAMES,
                created_at=r.created_at, updated_at=r.updated_at,
            )
            for r in rows
        ],
        meta=Meta(limit=params.limit, next_cursor=next_cur),
    )


@router.post("", response_model=RoleResponse, status_code=201)
async def create_role(
    body: RoleCreate,
    actor: dict = Depends(require_permission(Permission.MANAGE_ROLES)),
) -> RoleResponse:
    _validate_permissions(body.permissions)
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(select(Role).where(Role.name == body.name))
        ).scalar_one_or_none()
        if existing is not None:
            raise api_error(409, ErrorCode.CONFLICT, f"Role {body.name!r} already exists")

        role = Role(
            id=str(uuid.uuid4()),
            name=body.name,
            description=body.description,
            permissions=body.permissions,
        )
        session.add(role)
        await session.commit()
        await session.refresh(role)

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="role.create",
            target_type="role", target_id=role.id,
            after={"name": body.name, "permissions": body.permissions},
        )
    )
    return RoleResponse(
        id=role.id, name=role.name, description=role.description,
        permissions=role.permissions or [], user_count=0,
        is_static=role.name in STATIC_ROLE_NAMES,
        created_at=role.created_at, updated_at=role.updated_at,
    )


@router.patch("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    body: RoleUpdate,
    actor: dict = Depends(require_permission(Permission.MANAGE_ROLES)),
) -> RoleResponse:
    factory = get_session_factory()
    async with factory() as session:
        role = (
            await session.execute(select(Role).where(Role.id == role_id))
        ).scalar_one_or_none()
        if role is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Role not found")

        before = {"name": role.name, "description": role.description, "permissions": role.permissions}

        if body.name is not None and body.name != role.name:
            # Static roles cannot be renamed (would break the role-permission map)
            if role.name in STATIC_ROLE_NAMES:
                raise api_error(
                    409, ErrorCode.CONFLICT,
                    f"Cannot rename static role {role.name!r}",
                )
            # Reject duplicate name
            dup = (
                await session.execute(select(Role).where(Role.name == body.name, Role.id != role.id))
            ).scalar_one_or_none()
            if dup is not None:
                raise api_error(409, ErrorCode.CONFLICT, f"Role name {body.name!r} already in use")
            role.name = body.name
        if body.description is not None:
            role.description = body.description
        if body.permissions is not None:
            _validate_permissions(body.permissions)
            role.permissions = body.permissions

        await session.commit()
        await session.refresh(role)
        # Re-derive is_static (name may have changed)
        is_static = role.name in STATIC_ROLE_NAMES
        user_count = (
            await session.execute(
                select(func.count(UserRole.user_id)).where(UserRole.role_id == role.id)
            )
        ).scalar_one() or 0

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="role.update",
            target_type="role", target_id=role.id,
            before=before, after={"name": role.name, "description": role.description, "permissions": role.permissions},
        )
    )
    return RoleResponse(
        id=role.id, name=role.name, description=role.description,
        permissions=role.permissions or [], user_count=int(user_count),
        is_static=is_static,
        created_at=role.created_at, updated_at=role.updated_at,
    )


@router.delete("/{role_id}", status_code=204)
async def delete_role(
    role_id: str,
    actor: dict = Depends(require_permission(Permission.MANAGE_ROLES)),
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        role = (
            await session.execute(select(Role).where(Role.id == role_id))
        ).scalar_one_or_none()
        if role is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Role not found")

        # Block if any user holds this role
        user_count = (
            await session.execute(
                select(func.count(UserRole.user_id)).where(UserRole.role_id == role.id)
            )
        ).scalar_one() or 0
        if user_count > 0:
            raise api_error(
                409, ErrorCode.CONFLICT,
                f"Role {role.name!r} is held by {user_count} user(s); revoke all before deleting.",
            )

        await session.delete(role)
        await session.commit()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="role.delete",
            target_type="role", target_id=role_id, before={"name": role.name},
        )
    )


# === Re-exports of the per-role permission getter (test fixtures use it) ===
PERMISSION_GETTER = get_role_permissions
__all__ = ["PERMISSION_GETTER", "router"]
