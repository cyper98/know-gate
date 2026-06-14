"""Query embedder (bge-m3 with Redis cache).

Embeds the user's question via the same bge-m3 model the ingestion
pipeline uses (1024-dim, L2-normalized). Embeddings are cached in
Redis for 5 minutes keyed by sha256(query_text) — most users will
have at least one duplicate query within that window (the hot
topics widget relies on this).

The function is async because the cache is async (Redis); the actual
embed call is sync (CPU-bound under torch) and runs in a thread to
keep the event loop free.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from app.cache.helpers import get_query_embed, set_query_embed
from app.config import get_settings
from app.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    pass

logger = get_logger(__name__)


def _hash_query_text(text: str) -> str:
    """Stable cache key for a query string (sha256 hex)."""
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()


async def embed_query_cached(
    text: str,
    *,
    use_cache: bool = True,
) -> list[float]:
    """Embed a query with Redis-backed caching.

    Args:
        text: the user's question (raw, unpreprocessed)
        use_cache: set False to bypass the cache (e.g., for tests or
            when debugging a cache-poisoning issue)

    Returns:
        1024-dim list of floats (L2-normalized), suitable for Qdrant
        `query_points` directly.

    Raises:
        RuntimeError: if sentence-transformers is not installed
    """
    settings = get_settings()
    text_hash = _hash_query_text(text)

    if use_cache:
        cached = await get_query_embed(text_hash)
        if cached is not None:
            logger.debug("query_embed_cache_hit", text_hash=text_hash[:12])
            return cached

    # Cache miss — embed. The embedder is CPU-bound, run in a thread.
    import asyncio

    from app.pipeline.embedder import embed_query

    vec = await asyncio.to_thread(embed_query, text)

    if use_cache:
        await set_query_embed(text_hash, vec, ttl=settings.embedding_cache_ttl)
    return vec


__all__ = ["embed_query_cached"]
