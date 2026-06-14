"""Helper functions for scripts/init.py (kept separate to avoid importing
heavy client modules in the alembic env, which would create circular imports)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.enums import UserStatus
from app.db.models import AccessGroup, Role, SystemSettings, User, UserGroup, UserRole
from app.db.session import get_session_factory
from app.storage.buckets import init_documents_bucket
from app.vector.collections import init_chunks_collection
from argon2 import PasswordHasher

logger = logging.getLogger(__name__)
_hasher = PasswordHasher()


# === Default data (must match scripts/seed.py for consistency) ===
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
    {"name": "all-users", "description": "Every KnowGate user is in this group (default access)"},
    {"name": "engineering", "description": "Engineering team — engineering docs, specs, ADRs"},
]


async def init_qdrant_collection() -> None:
    """Create `chunks` collection with HNSW + payload indexes (idempotent)."""
    logger.info("init_qdrant_starting")
    await init_chunks_collection(force_recreate=False)
    logger.info("init_qdrant_done")


async def init_minio_bucket() -> None:
    """Create `documents` bucket with versioning (idempotent)."""
    logger.info("init_minio_starting")
    await init_documents_bucket()
    logger.info("init_minio_done")


async def seed_default_data() -> None:
    """Seed default roles, groups, admin user, settings (idempotent)."""
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        try:
            # === Roles ===
            for role_data in DEFAULT_ROLES:
                stmt = (
                    pg_insert(Role)
                    .values(**role_data)
                    .on_conflict_do_nothing(index_elements=["name"])
                )
                await session.execute(stmt)
            await session.flush()
            logger.info("seed_roles_done", count=len(DEFAULT_ROLES))

            # === Groups ===
            for group_data in DEFAULT_GROUPS:
                stmt = (
                    pg_insert(AccessGroup)
                    .values(**group_data)
                    .on_conflict_do_nothing(index_elements=["name"])
                )
                await session.execute(stmt)
            await session.flush()
            logger.info("seed_groups_done", count=len(DEFAULT_GROUPS))

            # === Admin user (idempotent) ===
            admin_email = settings.bootstrap_admin_email
            existing = await session.execute(
                __import__("sqlalchemy").select(User).where(User.email == admin_email)
            )
            if existing.scalar_one_or_none() is None:
                user = User(
                    email=admin_email,
                    display_name=settings.bootstrap_admin_name,
                    password_hash=_hasher.hash(settings.bootstrap_admin_password.get_secret_value()),
                    language_pref="en",
                    status=UserStatus.ACTIVE.value,
                )
                session.add(user)
                await session.flush()

                # Assign admin role
                admin_role_result = await session.execute(
                    __import__("sqlalchemy").select(Role).where(Role.name == "admin")
                )
                admin_role = admin_role_result.scalar_one_or_none()
                if admin_role:
                    session.add(
                        UserRole(
                            user_id=user.id,
                            role_id=admin_role.id,
                            granted_at=datetime.now(timezone.utc),
                        )
                    )

                # Assign to all-users + engineering
                for group_name in ("all-users", "engineering"):
                    grp_result = await session.execute(
                        __import__("sqlalchemy").select(AccessGroup).where(AccessGroup.name == group_name)
                    )
                    grp = grp_result.scalar_one_or_none()
                    if grp:
                        session.add(
                            UserGroup(
                                user_id=user.id,
                                group_id=grp.id,
                                joined_at=datetime.now(timezone.utc),
                            )
                        )
                logger.info("seed_admin_created", email=admin_email)
            else:
                logger.info("seed_admin_exists", email=admin_email)

            # === System settings (singleton) ===
            stmt = (
                pg_insert(SystemSettings)
                .values(id="1", default_language="en")
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await session.execute(stmt)
            await session.flush()
            logger.info("seed_settings_done")

            await session.commit()
        except Exception:
            await session.rollback()
            raise
