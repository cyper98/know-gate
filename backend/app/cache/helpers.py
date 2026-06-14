"""Redis helpers: get/set with TTL, JSON ser/de, sliding-window rate limit."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable
from typing import Any, TypeVar

from app.cache.client import get_redis_client
from app.cache.keys import (
    hot_queries_key,
    oauth_state_key,
    query_embed_key,
    query_result_key,
    rate_limit_ip_key,
    rate_limit_user_key,
    session_jti_key,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


# === Basic get/set with JSON ===
async def cache_get_json(key: str) -> Any | None:
    """Get value, JSON-deserialize. Returns None on miss."""
    client = get_redis_client()
    raw = await client.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def cache_set_json(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """Set value (JSON-serialize) with optional TTL."""
    client = get_redis_client()
    raw = json.dumps(value, default=str)
    if ttl_seconds:
        await client.set(key, raw, ex=ttl_seconds)
    else:
        await client.set(key, raw)


async def cache_delete(key: str) -> None:
    """Delete a key."""
    client = get_redis_client()
    await client.delete(key)


async def cache_ttl(key: str) -> int:
    """Get TTL in seconds (-1 if no TTL, -2 if key doesn't exist)."""
    client = get_redis_client()
    return int(await client.ttl(key))


# === Sliding-window rate limit ===
async def rate_limit_incr(
    key: str,
    window_seconds: int,
    limit: int,
) -> tuple[int, bool]:
    """Increment a counter with window expiry. Returns (current_count, is_allowed).

    Uses Redis ZSET for true sliding window (more accurate than fixed window).
    """
    import time

    client = get_redis_client()
    now = time.time()
    window_start = now - window_seconds

    # Remove old entries
    await client.zremrangebyscore(key, 0, window_start)

    # Add current
    await client.zadd(key, {f"{now}:{id}": now})

    # Set TTL on the key (1.5x window for safety)
    await client.expire(key, int(window_seconds * 1.5))

    # Get count
    count = int(await client.zcard(key))
    return (count, count <= limit)


# === Specific helpers (typed wrappers around cache_* + keys) ===
async def get_query_embed(text_hash: str) -> list[float] | None:
    return await cache_get_json(query_embed_key(text_hash))


async def set_query_embed(text_hash: str, vector: list[float], ttl: int = 300) -> None:
    await cache_set_json(query_embed_key(text_hash), vector, ttl)


async def get_query_result(query_hash: str, filter_hash: str) -> dict | None:
    return await cache_get_json(query_result_key(query_hash, filter_hash))


async def set_query_result(query_hash: str, filter_hash: str, result: dict, ttl: int = 86400) -> None:
    await cache_set_json(query_result_key(query_hash, filter_hash), result, ttl)


async def check_user_rate_limit(user_id: str, window: int, limit: int) -> tuple[int, bool]:
    return await rate_limit_incr(rate_limit_user_key(user_id, window), window, limit)


async def check_ip_rate_limit(ip: str, window: int, limit: int) -> tuple[int, bool]:
    return await rate_limit_incr(rate_limit_ip_key(ip, window), window, limit)


async def revoke_jti(jti: str, ttl_seconds: int) -> None:
    """Mark a JWT as revoked (TTL = remaining token lifetime)."""
    await cache_set_json(session_jti_key(jti), True, ttl_seconds)


async def is_jti_revoked(jti: str) -> bool:
    return bool(await cache_get_json(session_jti_key(jti)))


async def set_oauth_state(state: str, data: dict, ttl: int = 300) -> None:
    await cache_set_json(oauth_state_key(state), data, ttl)


async def pop_oauth_state(state: str) -> dict | None:
    """Atomically get + delete (one-time use)."""
    client = get_redis_client()
    async with client.pipeline(transaction=True) as pipe:
        await pipe.get(oauth_state_key(state))
        await pipe.delete(oauth_state_key(state))
        results = await pipe.execute()
    raw = results[0]
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def track_query(query_hash: str, weight: float = 1.0) -> None:
    """Track a query for the hot topics widget (sorted set by score)."""
    client = get_redis_client()
    key = hot_queries_key()
    await client.zincrby(key, weight, query_hash)


async def get_hot_queries(top_n: int = 10) -> list[tuple[str, float]]:
    """Get top N hot queries (hash, count)."""
    client = get_redis_client()
    raw = await client.zrevrange(hot_queries_key(), 0, top_n - 1, withscores=True)
    return [(member, float(score)) for member, score in raw]


__all__ = [
    "cache_get_json",
    "cache_set_json",
    "cache_delete",
    "cache_ttl",
    "rate_limit_incr",
    "get_query_embed",
    "set_query_embed",
    "get_query_result",
    "set_query_result",
    "check_user_rate_limit",
    "check_ip_rate_limit",
    "revoke_jti",
    "is_jti_revoked",
    "set_oauth_state",
    "pop_oauth_state",
    "track_query",
    "get_hot_queries",
]
