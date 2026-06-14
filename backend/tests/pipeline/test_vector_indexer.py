"""Unit tests for the Qdrant indexer (bulk upsert + helpers)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client.http import models as qmodels

from app.vector.indexer import (
    BULK_BATCH_SIZE,
    make_point_id,
    upsert_chunks_bulk,
)


def test_make_point_id_is_deterministic() -> None:
    """Same (doc_id, chunk_index) → same UUID v5 (idempotency for re-index)."""
    a = make_point_id("doc-1", 0)
    b = make_point_id("doc-1", 0)
    assert a == b
    assert len(a) == 36  # UUID string length


def test_make_point_id_differs_for_different_chunks() -> None:
    a = make_point_id("doc-1", 0)
    b = make_point_id("doc-1", 1)
    assert a != b


def test_make_point_id_differs_for_different_docs() -> None:
    a = make_point_id("doc-1", 0)
    b = make_point_id("doc-2", 0)
    assert a != b


@pytest.mark.asyncio
async def test_upsert_chunks_bulk_empty_returns_zero() -> None:
    client = MagicMock()
    n = await upsert_chunks_bulk(client, [])
    assert n == 0
    client.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_chunks_bulk_single_batch() -> None:
    """A small batch (< 500) goes in one upsert call."""
    client = MagicMock()
    client.upsert = AsyncMock()

    points = [
        qmodels.PointStruct(id=f"p-{i}", vector=[0.0] * 4, payload={})
        for i in range(10)
    ]
    n = await upsert_chunks_bulk(client, points)
    assert n == 10
    assert client.upsert.await_count == 1
    client.upsert.assert_awaited_with(collection_name="chunks", points=points)


@pytest.mark.asyncio
async def test_upsert_chunks_bulk_multi_batch() -> None:
    """A batch > 500 must be split across multiple upsert calls."""
    client = MagicMock()
    client.upsert = AsyncMock()

    n_points = BULK_BATCH_SIZE + 100  # 600 → 2 calls
    points = [
        qmodels.PointStruct(id=f"p-{i}", vector=[0.0] * 4, payload={})
        for i in range(n_points)
    ]
    n = await upsert_chunks_bulk(client, points)
    assert n == n_points
    assert client.upsert.await_count == 2

    # First call: full batch, second call: 100 points
    first_call = client.upsert.await_args_list[0]
    second_call = client.upsert.await_args_list[1]
    assert len(first_call.kwargs["points"]) == BULK_BATCH_SIZE
    assert len(second_call.kwargs["points"]) == 100


@pytest.mark.asyncio
async def test_upsert_chunks_bulk_custom_batch_size() -> None:
    """`batch_size` kwarg overrides the default 500."""
    client = MagicMock()
    client.upsert = AsyncMock()

    points = [qmodels.PointStruct(id=f"p-{i}", vector=[0.0] * 4, payload={}) for i in range(7)]
    n = await upsert_chunks_bulk(client, points, batch_size=3)
    assert n == 7
    # 7 / 3 = ceil(2.33) = 3 batches (3, 3, 1)
    assert client.upsert.await_count == 3
