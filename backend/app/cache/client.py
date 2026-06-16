"""Async Redis client init + health check."""

from __future__ import annotations


import redis.asyncio as aioredis

from app.config import get_settings

from app.logging import get_logger

logger = get_logger(__name__)

_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Lazy-init singleton async Redis client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
        logger.info("redis_client_initialized", url=settings.redis_url.split("@")[-1])  # hide password
    return _client


async def check_redis() -> bool:
    """Verify Redis is reachable. Returns True if PING works."""
    try:
        client = get_redis_client()
        return bool(await client.ping())
    except Exception as e:
        logger.error("redis_health_check_failed", error=str(e))
        return False


async def close_redis() -> None:
    """Close Redis client (for shutdown)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
