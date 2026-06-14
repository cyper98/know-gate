"""Async SQLAlchemy session factory + FastAPI dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


def _make_engine(settings: Settings) -> AsyncEngine:
    """Create async engine with pool sized per env (dev=5, prod=20)."""
    pool_size = 5 if settings.is_development else 20
    return create_async_engine(
        settings.database_url_async,
        pool_size=pool_size,
        max_overflow=10,
        pool_pre_ping=True,  # Detect dead connections
        pool_recycle=3600,   # Recycle every hour
        echo=settings.is_development and settings.kg_log_level == "DEBUG",
    )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazy-init singleton engine."""
    global _engine
    if _engine is None:
        _engine = _make_engine(get_settings())
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Lazy-init singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield async session, auto-close on exit.

    Usage in endpoint:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Type alias for FastAPI deps
DBSession = Annotated[AsyncSession, Depends(get_db)]
