"""Unit tests for the query embedder (cache + embed)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_embedder() -> None:
    from app.pipeline import embedder
    embedder.reset_for_tests()
    yield
    embedder.reset_for_tests()


@pytest.mark.asyncio
async def test_embed_query_cached_returns_embedding() -> None:
    """On cache miss, embed the query and return the vector."""
    fake_vec = [0.1] * 1024
    with patch(
        "app.retrieval.query_embedder.get_query_embed",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.retrieval.query_embedder.set_query_embed",
        new=AsyncMock(),
    ), patch(
        "app.pipeline.embedder.embed_query",
        return_value=fake_vec,
    ):
        from app.retrieval.query_embedder import embed_query_cached
        vec = await embed_query_cached("hello world")
    assert vec == fake_vec


@pytest.mark.asyncio
async def test_embed_query_cached_returns_cached_when_present() -> None:
    """On cache hit, skip the embed call entirely."""
    cached = [0.5] * 1024
    with patch(
        "app.retrieval.query_embedder.get_query_embed",
        new=AsyncMock(return_value=cached),
    ), patch(
        "app.pipeline.embedder.embed_query",
    ) as mock_embed:
        from app.retrieval.query_embedder import embed_query_cached
        vec = await embed_query_cached("cached query")
    assert vec == cached
    mock_embed.assert_not_called()


@pytest.mark.asyncio
async def test_embed_query_cached_bypass_skips_cache() -> None:
    """`use_cache=False` skips the cache read and the write."""
    fake_vec = [0.0] * 1024
    with patch(
        "app.retrieval.query_embedder.get_query_embed",
        new=AsyncMock(return_value=[0.9] * 1024),  # would normally return
    ), patch(
        "app.retrieval.query_embedder.set_query_embed",
        new=AsyncMock(),
    ) as mock_set, patch(
        "app.pipeline.embedder.embed_query",
        return_value=fake_vec,
    ):
        from app.retrieval.query_embedder import embed_query_cached
        vec = await embed_query_cached("bypass", use_cache=False)
    assert vec == fake_vec
    mock_set.assert_not_called()
