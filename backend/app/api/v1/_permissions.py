"""Shared permission helpers for v1 routers.

The functions here centralize:
- "Is this user an admin?" (role-level shortcut for bypassing data filters)
- "Load the user's group IDs" (for document-level data filters)
- "Does this user have at least one group in common with this document?" (data-level check)

Why not bake into `app.auth.permissions`:
- `app.auth.permissions` only knows about ROLES (RBAC). It doesn't know
  about ACCESS GROUPS, which are a separate, orthogonal data filter.
- Keeping these helpers next to the routers that use them avoids
  circular imports (db models <-> auth).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Document, User, UserGroup

ADMIN_ROLES = frozenset({"admin"})


def has_admin_role(user: dict) -> bool:
    """True if the caller's JWT carries the `admin` role (any flavor)."""
    roles = user.get("roles") or []
    return any(r in ADMIN_ROLES for r in roles)


async def user_group_ids(session: AsyncSession, user_id: str) -> list[str]:
    """Return the list of access-group IDs the user belongs to.

    Empty list = the user sees no documents (admin role bypasses this).
    """
    from sqlalchemy import select

    rows = (
        await session.execute(
            select(UserGroup.group_id).where(UserGroup.user_id == user_id)
        )
    ).all()
    return [row[0] for row in rows]


def user_has_doc_access(group_ids: list[str] | None, doc: Document) -> bool:
    """True if the user has at least one access group in common with the document.

    `group_ids` should be the caller's group IDs (use `user_group_ids(session, user_id)`).
    Caller MUST ensure `doc.access_groups` is eagerly loaded (via `selectinload`).
    """
    if not group_ids:
        return False
    doc_groups = {g.id for g in doc.access_groups}
    return bool(set(group_ids) & doc_groups)


async def load_user_with_groups(
    session: AsyncSession, user_id: str
) -> User | None:
    """Load a user with their `groups` relationship eagerly populated."""
    from sqlalchemy import select

    result = await session.execute(
        select(User)
        .options(selectinload(User.groups))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


__all__ = [
    "ADMIN_ROLES",
    "has_admin_role",
    "load_user_with_groups",
    "user_group_ids",
    "user_has_doc_access",
]
