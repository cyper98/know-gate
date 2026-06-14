"""Semantic cache for query results (Redis-backed).

Caches the FULL pipeline output (answer + citations + warnings) for
a given (query_text, group_ids_hash) combination. TTL = 24h by
default (per architecture §4.3 Caching Strategy).

Cache key:
- `query_hash` = sha256(query_text) — same query = same key
- `filter_hash` = sha256(sorted(group_ids) + language) — different
  permission context = different answer (so user A's cache doesn't
  leak to user B)

Note: this is a KEY-based cache, not a semantic-similarity cache.
The architecture's "semantic cache" wording is aspirational; the
minimum viable implementation is a deterministic-key cache. A
true semantic-similarity cache (embed the query, find nearest
cached query above cosine threshold) is a follow-up.

Invalidation:
- TTL expiry (24h)
- Explicit delete on doc re-index (call `invalidate_for_doc(doc_id)`
  — but that requires a reverse-index of which keys touched which
  docs; deferred — TTL is the only mechanism in MVP)
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from app.cache.helpers import get_query_result, set_query_result
from app.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    pass

logger = get_logger(__name__)

# 24 hours (per architecture §4.3)
DEFAULT_TTL_SECONDS = 86400


def cache_key_for_query(
    query_text: str,
    *,
    group_ids: list[str] | tuple[str, ...] = (),
    language: str = "en",
) -> tuple[str, str]:
    """Return (query_hash, filter_hash) for a query + permission context.

    The cache key combines both: same question but different groups
    yields a different cached answer.
    """
    q_hash = hashlib.sha256(query_text.strip().lower().encode("utf-8")).hexdigest()
    # Sort group_ids for order-independent hashing
    gid_str = ",".join(sorted(str(g) for g in group_ids))
    f_hash = hashlib.sha256(f"{gid_str}|{language}".encode()).hexdigest()
    return q_hash, f_hash


class SemanticCache:
    """Read-through cache for query results.

    `get()` returns a deserialized `QueryResult` (or None on miss).
    `set()` serializes a result and stores it with the configured TTL.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._ttl = ttl_seconds or DEFAULT_TTL_SECONDS

    async def get(
        self,
        query_text: str,
        *,
        group_ids: list[str] | tuple[str, ...],
        language: str,
    ) -> dict | None:
        """Return the cached result dict, or None on miss."""
        q_hash, f_hash = cache_key_for_query(
            query_text, group_ids=group_ids, language=language
        )
        result = await get_query_result(q_hash, f_hash)
        if result is not None:
            logger.debug(
                "semantic_cache_hit",
                query_hash=q_hash[:12],
                filter_hash=f_hash[:12],
            )
        return result

    async def set(
        self,
        query_text: str,
        *,
        group_ids: list[str] | tuple[str, ...],
        language: str,
        result: Any,
    ) -> None:
        """Store a result in the cache (TTL = 24h by default)."""
        q_hash, f_hash = cache_key_for_query(
            query_text, group_ids=group_ids, language=language
        )
        # We accept either a dict or a dataclass-like with `to_dict`.
        if hasattr(result, "to_dict"):
            payload = result.to_dict()
        elif hasattr(result, "__dict__"):
            payload = asdict(result) if hasattr(result, "__dataclass_fields__") else dict(result.__dict__)
        else:
            payload = dict(result)
        await set_query_result(q_hash, f_hash, payload, ttl=self._ttl)
        logger.debug(
            "semantic_cache_set",
            query_hash=q_hash[:12],
            filter_hash=f_hash[:12],
            ttl=self._ttl,
        )


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "SemanticCache",
    "cache_key_for_query",
]
