"""Seed default data: 1 admin user, 3 roles, 2 access groups, system_settings singleton.

Idempotent: re-runs don't duplicate rows (uses ON CONFLICT DO NOTHING).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Allow `python -m scripts.seed` from backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.enums import UserStatus
from app.db.models import (
    AccessGroup,
    Role,
    SystemSettings,
    User,
    UserGroup,
    UserRole,
)
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)
settings = get_settings()
_hasher = PasswordHasher()


# === Default data ===
DEFAULT_ROLES = [
    {
        "name": "admin",
        "description": "Full access: manage users, roles, groups, sources, settings, all docs",
        "permissions": [
            "view_doc", "edit_doc_metadata", "delete_doc",
            "manage_users", "manage_roles", "manage_groups",
            "manage_sources", "manage_settings", "invite_user",
            "view_audit_log",
        ],
    },
    {
        "name": "editor",
        "description": "Can view + edit doc metadata; cannot manage users/roles/groups",
        "permissions": ["view_doc", "edit_doc_metadata"],
    },
    {
        "name": "member",
        "description": "Read-only: view docs in groups they belong to",
        "permissions": ["view_doc"],
    },
]

DEFAULT_GROUPS = [
    {
        "name": "all-users",
        "description": "Every KnowGate user is in this group (default access)",
    },
    {
        "name": "engineering",
        "description": "Engineering team — engineering docs, specs, ADRs",
    },
]

DEFAULT_ADMIN = {
    "email": settings.bootstrap_admin_email,
    "display_name": settings.bootstrap_admin_name,
    "password": settings.bootstrap_admin_password.get_secret_value(),
    "status": UserStatus.ACTIVE.value,
}


def _hash_password(plaintext: str) -> str:
    """Argon2id hash per OWASP recommendation."""
    return _hasher.hash(plaintext)


async def seed_roles(session: AsyncSession) -> dict[str, str]:
    """Insert default roles if not present. Returns name -> id map."""
    name_to_id: dict[str, str] = {}

    for role_data in DEFAULT_ROLES:
        stmt = (
            pg_insert(Role)
            .values(**role_data)
            .on_conflict_do_nothing(index_elements=["name"])
            .returning(Role.id, Role.name)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row:
            name_to_id[row.name] = row.id
        else:
            # Already exists, fetch id
            existing = await session.execute(
                select(Role.id, Role.name).where(Role.name == role_data["name"])
            )
            erow = existing.first()
            if erow:
                name_to_id[erow.name] = erow.id

    await session.flush()
    return name_to_id


async def seed_groups(session: AsyncSession) -> dict[str, str]:
    """Insert default access groups. Returns name -> id map."""
    name_to_id: dict[str, str] = {}

    for group_data in DEFAULT_GROUPS:
        stmt = (
            pg_insert(AccessGroup)
            .values(**group_data)
            .on_conflict_do_nothing(index_elements=["name"])
            .returning(AccessGroup.id, AccessGroup.name)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row:
            name_to_id[row.name] = row.id
        else:
            existing = await session.execute(
                select(AccessGroup.id, AccessGroup.name).where(AccessGroup.name == group_data["name"])
            )
            erow = existing.first()
            if erow:
                name_to_id[erow.name] = erow.id

    await session.flush()
    return name_to_id


async def seed_admin_user(
    session: AsyncSession, role_map: dict[str, str], group_map: dict[str, str]
) -> str | None:
    """Create bootstrap admin user (idempotent). Returns user id or None if exists."""
    admin_email = DEFAULT_ADMIN["email"]

    # Check if user exists
    existing = await session.execute(select(User).where(User.email == admin_email))
    existing_user = existing.scalar_one_or_none()
    if existing_user is not None:
        logger.info("seed_admin_exists", email=admin_email)
        return existing_user.id

    # Create user
    user = User(
        email=admin_email,
        display_name=DEFAULT_ADMIN["display_name"],
        password_hash=_hash_password(DEFAULT_ADMIN["password"]),
        language_pref=(settings.kg_env and "en") or "en",
        status=UserStatus.ACTIVE.value,
    )
    session.add(user)
    await session.flush()

    user_id = user.id
    logger.info("seed_admin_created", email=admin_email, id=user_id)

    # Assign admin role
    admin_role_id = role_map.get("admin")
    if admin_role_id:
        session.add(UserRole(user_id=user_id, role_id=admin_role_id, granted_at=__import__("datetime").datetime.utcnow()))
        await session.flush()
        logger.info("seed_admin_role_assigned", role="admin")

    # Assign to all-users + engineering
    for group_name in ("all-users", "engineering"):
        group_id = group_map.get(group_name)
        if group_id:
            session.add(UserGroup(user_id=user_id, group_id=group_id, joined_at=__import__("datetime").datetime.utcnow()))
            await session.flush()
    logger.info("seed_admin_groups_assigned", groups=["all-users", "engineering"])

    return user_id


async def seed_settings(session: AsyncSession) -> None:
    """Create system_settings singleton (id=1) if not present."""
    stmt = (
        pg_insert(SystemSettings)
        .values(id="1", default_language="en")
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await session.execute(stmt)
    await session.flush()
    logger.info("seed_settings_created")


async def run_seed() -> None:
    """Run all seed steps in a single transaction."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            role_map = await seed_roles(session)
            logger.info("seed_roles_done", count=len(role_map), roles=list(role_map.keys()))

            group_map = await seed_groups(session)
            logger.info("seed_groups_done", count=len(group_map), groups=list(group_map.keys()))

            await seed_admin_user(session, role_map, group_map)
            await seed_settings(session)

            await session.commit()
            logger.info("seed_complete")
        except Exception:
            await session.rollback()
            logger.exception("seed_failed")
            raise


def main() -> None:
    """CLI entry: `python -m scripts.seed`"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
