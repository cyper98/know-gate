"""DB initialization helpers (create_all for dev, verify for prod).

In production, run migrations via `alembic upgrade head` instead of create_all.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.db.session import get_engine

logger = logging.getLogger(__name__)


async def check_connection() -> bool:
    """Verify DB is reachable. Returns True if SELECT 1 works."""
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("db_connection_check_failed", error=str(e))
        return False


async def init_db() -> None:
    """Initialize DB schema (dev only — use Alembic in prod).

    In production, run `alembic upgrade head` before app starts.
    This is a safety net for dev environments.
    """
    from app.db.models import Base  # Import here to register all models

    if not await check_connection():
        raise RuntimeError("Cannot connect to DB; check connection settings")

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("db_schema_initialized", tables=len(Base.metadata.tables))


def main() -> None:
    """CLI entry: `python -m app.db.init`"""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(init_db())


if __name__ == "__main__":
    main()
