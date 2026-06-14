"""Users API (7 routes).

- GET    /users                    — list (admin)
- POST   /users                    — invite (admin, sends a magic link / sets initial password)
- GET    /users/{id}               — detail (admin)
- PATCH  /users/{id}               — update display_name / language_pref / status (admin)
- DELETE /users/{id}               — soft-delete (GDPR) (admin)
- POST   /users/{id}/roles         — assign role (admin)
- DELETE /users/{id}/roles/{rid}   — revoke role (admin)

All endpoints require admin role via the MANAGE_USERS permission.

Notes:
- We do NOT expose `password_hash` in any response.
- Soft-delete sets `status=deleted` (UserStatus.DELETED). The row stays
  in the DB for the audit retention window, then is hard-deleted by a
  scheduled job.
- Role assignment is upsert-style via the `user_roles` PK
  (user_id, role_id). Removing the last admin role for the only
  admin user is blocked (E6 conflict) to prevent lockout.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi import Query as QueryParam
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.errors import api_error
from app.api.pagination import PageParams, decode_cursor, encode_cursor
from app.api.responses import ErrorCode, Meta, Page
from app.audit.log import log_event
from app.auth.password import hash_password
from app.auth.permissions import Permission, require_permission
from app.db.enums import UserStatus
from app.db.models import AccessGroup, Role, User, UserGroup, UserRole
from app.db.session import get_session_factory
from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


# === Schemas ===

class UserSummary(BaseModel):
    """User summary (no password hash, no group list — that lives elsewhere)."""

    id: str
    email: str
    display_name: str
    language_pref: str
    status: str
    last_login_at: datetime | None
    roles: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserDetail(UserSummary):
    """Same as summary for now; reserved for richer detail (groups, last IP, etc.)."""

    groups: list[str] = Field(default_factory=list, description="Access group IDs")


class UserInviteResponse(UserDetail):
    """Invite response extends UserDetail with the one-time plaintext password.

    The plaintext password is returned ONCE in the response — the caller
    (admin) is expected to share it with the new user through a secure
    out-of-band channel. The server only stores the argon2 hash.
    """
    initial_password: str


class UserInviteRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    roles: list[str] = Field(
        default_factory=lambda: ["member"],
        description="Role names to assign (e.g., 'admin', 'editor', 'member').",
    )
    initial_password: str | None = Field(
        default=None,
        min_length=8, max_length=128,
        description="Optional initial password. If omitted, a random one is generated and returned ONCE.",
    )
    group_ids: list[str] | None = Field(
        default=None, description="Access groups to add the user to.",
    )


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    language_pref: str | None = Field(default=None, min_length=2, max_length=8)
    status: UserStatus | None = None


class RoleAssignRequest(BaseModel):
    role_id: str | None = Field(default=None, description="Role UUID")
    role_name: str | None = Field(default=None, description="Role name (alternative to role_id)")


# === Endpoints ===

@router.get("", response_model=Page[UserSummary])
async def list_users(
    _user: dict = Depends(require_permission(Permission.MANAGE_USERS)),
    params: PageParams = Depends(),
    status_filter: UserStatus | None = QueryParam(default=None, alias="status"),
    email_contains: str | None = QueryParam(default=None, max_length=200),
) -> Page[UserSummary]:
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(User).order_by(User.created_at.desc(), User.id.desc())
        if status_filter:
            stmt = stmt.where(User.status == status_filter.value)
        if email_contains:
            stmt = stmt.where(User.email.ilike(f"%{email_contains}%"))

        if params.cursor:
            try:
                ts, uid = decode_cursor(params.cursor)
            except ValueError:
                raise api_error(400, ErrorCode.BAD_REQUEST, "Invalid cursor") from None
            stmt = stmt.where(
                (User.created_at < ts) | ((User.created_at == ts) & (User.id < uid))
            )
        stmt = stmt.limit(params.limit + 1)
        rows = (await session.execute(stmt)).scalars().all()
        has_more = len(rows) > params.limit
        rows = rows[: params.limit]
        next_cur = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None

        # Load role names in one query
        user_ids = [u.id for u in rows]
        role_map: dict[str, list[str]] = {uid: [] for uid in user_ids}
        if user_ids:
            role_rows = (
                await session.execute(
                    select(UserRole.user_id, Role.name)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(UserRole.user_id.in_(user_ids))
                )
            ).all()
            for uid, rname in role_rows:
                role_map[uid].append(rname)

    return Page(
        data=[
            UserSummary(
                id=u.id,
                email=u.email,
                display_name=u.display_name,
                language_pref=u.language_pref,
                status=u.status,
                last_login_at=u.last_login_at,
                roles=role_map.get(u.id, []),
                created_at=u.created_at,
                updated_at=u.updated_at,
            )
            for u in rows
        ],
        meta=Meta(limit=params.limit, next_cursor=next_cur),
    )


@router.post("", response_model=UserInviteResponse, status_code=201)
async def invite_user(
    body: UserInviteRequest,
    actor: dict = Depends(require_permission(Permission.MANAGE_USERS)),
) -> UserInviteResponse:
    """Create a user, assign roles, optionally add to groups.

    If `initial_password` is omitted, a random 24-char password is
    generated and returned ONCE in the response (the only time it's
    available — the hash is stored, plaintext is never persisted).
    """
    factory = get_session_factory()
    async with factory() as session:
        # Reject duplicate email
        existing = (
            await session.execute(select(User).where(User.email == body.email))
        ).scalar_one_or_none()
        if existing is not None:
            raise api_error(
                409, ErrorCode.CONFLICT,
                f"A user with email {body.email} already exists",
            )

        # Validate roles (must exist)
        if body.roles:
            r = (
                await session.execute(select(Role).where(Role.name.in_(body.roles)))
            ).scalars().all()
            found_names = {x.name for x in r}
            missing = set(body.roles) - found_names
            if missing:
                raise api_error(
                    400, ErrorCode.BAD_REQUEST,
                    f"Unknown role(s): {sorted(missing)}",
                )

        plain = body.initial_password or secrets.token_urlsafe(18)[:24]
        user = User(
            id=str(uuid.uuid4()),
            email=body.email,
            display_name=body.display_name,
            password_hash=hash_password(plain),
            language_pref="en",
            status=UserStatus.ACTIVE.value,
        )
        session.add(user)
        await session.flush()

        # Assign roles
        for rn in (body.roles or ["member"]):
            r = (await session.execute(select(Role).where(Role.name == rn))).scalar_one()
            session.add(UserRole(user_id=user.id, role_id=r.id, granted_at=datetime.now(UTC), granted_by=actor["id"]))

        # Add to groups
        if body.group_ids:
            grp_rows = (
                await session.execute(
                    select(AccessGroup).where(AccessGroup.id.in_(body.group_ids))
                )
            ).scalars().all()
            for g in grp_rows:
                session.add(UserGroup(user_id=user.id, group_id=g.id, joined_at=datetime.now(UTC)))

        await session.commit()

        # Audit
        asyncio.create_task(  # noqa: RUF006 — fire-and-forget
            log_event(
                actor_id=actor["id"],
                actor_email=None,
                action="user.invite",
                target_type="user",
                target_id=user.id,
                after={"email": body.email, "roles": body.roles, "groups": body.group_ids or []},
            )
        )

        # Build response (include the one-time plaintext password for the admin to share)
        return UserInviteResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            language_pref=user.language_pref,
            status=user.status,
            last_login_at=None,
            roles=body.roles or ["member"],
            groups=body.group_ids or [],
            created_at=user.created_at,
            updated_at=user.updated_at,
            initial_password=plain,
        )


@router.get("/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: str,
    _user: dict = Depends(require_permission(Permission.MANAGE_USERS)),
) -> UserDetail:
    factory = get_session_factory()
    async with factory() as session:
        u = (
            await session.execute(
                select(User)
                .options(selectinload(User.groups), selectinload(User.user_roles))
                .where(User.id == user_id)
            )
        ).scalar_one_or_none()
        if u is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "User not found")
        role_names = (
            await session.execute(
                select(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == u.id)
            )
        ).scalars().all()
    return UserDetail(
        id=u.id, email=u.email, display_name=u.display_name,
        language_pref=u.language_pref, status=u.status, last_login_at=u.last_login_at,
        roles=list(role_names), groups=[g.id for g in u.groups],
        created_at=u.created_at, updated_at=u.updated_at,
    )


@router.patch("/{user_id}", response_model=UserDetail)
async def update_user(
    user_id: str,
    body: UserUpdate,
    actor: dict = Depends(require_permission(Permission.MANAGE_USERS)),
) -> UserDetail:
    factory = get_session_factory()
    async with factory() as session:
        u = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if u is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "User not found")

        # Block suspending/deleting the last active admin (avoid lockout)
        current_roles = await _user_role_names(session, u.id)
        if (
            body.status in (UserStatus.SUSPENDED, UserStatus.DELETED)
            and "admin" in current_roles
        ):
            active_admins = (
                await session.execute(
                    select(func.count(User.id))
                    .join(UserRole, UserRole.user_id == User.id)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(
                        Role.name == "admin",
                        User.status == UserStatus.ACTIVE.value,
                        User.id != u.id,
                    )
                )
            ).scalar_one() or 0
            if active_admins == 0:
                raise api_error(
                    409, ErrorCode.CONFLICT,
                    "Cannot suspend or delete the last active admin (would lock out the system).",
                )

        before = {"status": u.status, "display_name": u.display_name, "language_pref": u.language_pref}
        if body.display_name is not None:
            u.display_name = body.display_name
        if body.language_pref is not None:
            u.language_pref = body.language_pref
        if body.status is not None:
            u.status = body.status.value
        await session.commit()
        await session.refresh(u)
        role_names = (
            await session.execute(
                select(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == u.id)
            )
        ).scalars().all()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="user.update",
            target_type="user", target_id=u.id,
            before=before, after={"status": u.status, "display_name": u.display_name, "language_pref": u.language_pref},
        )
    )
    return UserDetail(
        id=u.id, email=u.email, display_name=u.display_name,
        language_pref=u.language_pref, status=u.status, last_login_at=u.last_login_at,
        roles=list(role_names), groups=[g.id for g in u.groups],
        created_at=u.created_at, updated_at=u.updated_at,
    )


@router.delete("/{user_id}", status_code=204)
async def soft_delete_user(
    user_id: str,
    actor: dict = Depends(require_permission(Permission.MANAGE_USERS)),
) -> None:
    """Soft-delete (GDPR). Sets status=deleted; the row is hard-deleted by a cron after retention."""
    factory = get_session_factory()
    async with factory() as session:
        u = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if u is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "User not found")

        # Same last-admin guard
        ur_role_names = await _user_role_names(session, u.id)
        if "admin" in ur_role_names:
            active_admins = (
                await session.execute(
                    select(func.count(User.id))
                    .join(UserRole, UserRole.user_id == User.id)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(Role.name == "admin", User.status == UserStatus.ACTIVE.value, User.id != u.id)
                )
            ).scalar_one() or 0
            if active_admins == 0:
                raise api_error(
                    409, ErrorCode.CONFLICT,
                    "Cannot delete the last active admin.",
                )

        u.status = UserStatus.DELETED.value
        await session.commit()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="user.delete",
            target_type="user", target_id=u.id, before={"status": "active"},
        )
    )


@router.post("/{user_id}/roles", status_code=201)
async def assign_role(
    user_id: str,
    body: RoleAssignRequest,
    actor: dict = Depends(require_permission(Permission.MANAGE_USERS)),
) -> dict:
    """Assign a role to a user (idempotent — re-assigning the same role is a no-op)."""
    if not body.role_id and not body.role_name:
        raise api_error(400, ErrorCode.BAD_REQUEST, "Either role_id or role_name is required")

    factory = get_session_factory()
    async with factory() as session:
        # Resolve role
        if body.role_id:
            role = (await session.execute(select(Role).where(Role.id == body.role_id))).scalar_one_or_none()
        else:
            role = (await session.execute(select(Role).where(Role.name == body.role_name))).scalar_one_or_none()
        if role is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Role not found")

        # Verify user exists
        u = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if u is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "User not found")

        # Check if the user already has this role (idempotent re-assignment
        # is a no-op — we don't pollute the audit log with redundant entries)
        from sqlalchemy import and_, exists

        already_has = (
            await session.execute(
                select(
                    exists().where(
                        and_(UserRole.user_id == u.id, UserRole.role_id == role.id)
                    )
                )
            )
        ).scalar()

        if already_has:
            # No-op: re-assigning a role the user already holds.
            return {"user_id": u.id, "role": role.name, "role_id": role.id, "noop": True}

        # Upsert (ignore if exists)
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(UserRole).values(
            user_id=u.id, role_id=role.id, granted_at=datetime.now(UTC), granted_by=actor["id"]
        ).on_conflict_do_nothing(index_elements=["user_id", "role_id"])
        await session.execute(stmt)
        await session.commit()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="user.role.assign",
            target_type="user", target_id=u.id, after={"role": role.name},
        )
    )
    return {"user_id": u.id, "role": role.name, "role_id": role.id}


@router.delete("/{user_id}/roles/{role_id}", status_code=204)
async def revoke_role(
    user_id: str,
    role_id: str,
    actor: dict = Depends(require_permission(Permission.MANAGE_USERS)),
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        # Resolve role (for the audit log message)
        role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
        if role is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "Role not found")

        # Last-admin guard
        if role.name == "admin":
            active_admins = (
                await session.execute(
                    select(func.count(User.id))
                    .join(UserRole, UserRole.user_id == User.id)
                    .where(
                        UserRole.role_id == role_id,
                        User.status == UserStatus.ACTIVE.value,
                        User.id != user_id,
                    )
                )
            ).scalar_one() or 0
            if active_admins == 0:
                raise api_error(
                    409, ErrorCode.CONFLICT,
                    "Cannot revoke the last active admin's admin role.",
                )

        from sqlalchemy import delete as sql_delete

        await session.execute(
            sql_delete(UserRole).where(
                UserRole.user_id == user_id, UserRole.role_id == role_id
            )
        )
        await session.commit()

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget
        log_event(
            actor_id=actor["id"], actor_email=None, action="user.role.revoke",
            target_type="user", target_id=user_id, before={"role": role.name},
        )
    )


# === Helpers ===

async def _user_role_names(session: Any, user_id: str) -> list[str]:
    rows = (
        await session.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
    ).scalars().all()
    return list(rows)


__all__ = ["router"]
