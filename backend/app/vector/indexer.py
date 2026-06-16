"""Qdrant indexer (single + bulk upsert, delete, mark status).

The ingestion pipeline calls `upsert_chunks_bulk` with hundreds of
chunks per doc; the basic `upsert_chunk` is kept for one-off tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.vector.collections import CHUNKS_COLLECTION
from app.vector.payload_schema import ChunkPayload, PayloadStatus

from app.logging import get_logger

logger = get_logger(__name__)

# How many points to send in a single Qdrant upsert call.
# 500 is the sweet spot from the Qdrant docs for write-heavy workloads.
BULK_BATCH_SIZE = 500


def _make_point_id(doc_id: str, chunk_index: int) -> str:
    """Deterministic UUID v5 from (doc_id, chunk_index) — same chunk always has same Qdrant id."""
    ns = uuid.UUID("00000000-0000-0000-0000-000000000001")
    return str(uuid.uuid5(ns, f"{doc_id}:{chunk_index}"))


def make_point_id(doc_id: str, chunk_index: int) -> str:
    """Public alias for `_make_point_id` (the pipeline orchestrator uses this)."""
    return _make_point_id(doc_id, chunk_index)


async def upsert_chunk(
    client: AsyncQdrantClient,
    chunk_id: str,
    doc_id: str,
    chunk_index: int,
    vector: list[float],
    payload: ChunkPayload,
) -> str:
    """Upsert one chunk to Qdrant. Returns the Qdrant point id (deterministic UUID v5)."""
    point_id = _make_point_id(doc_id, chunk_index)

    await client.upsert(
        collection_name=CHUNKS_COLLECTION,
        points=[
            qmodels.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "chunk_id": chunk_id,
                    "doc_id": payload.doc_id,
                    "group_ids": payload.group_ids,
                    "language": payload.language,
                    "status": payload.status,
                    "chunk_index": payload.chunk_index,
                    "section_title": payload.section_title,
                    "indexed_at": payload.indexed_at,
                    "source": payload.source,
                    "source_id": payload.source_id,
                },
            )
        ],
    )
    return point_id


async def upsert_chunks_bulk(
    client: AsyncQdrantClient,
    points: Sequence[qmodels.PointStruct],
    *,
    batch_size: int = BULK_BATCH_SIZE,
) -> int:
    """Upsert many points in batches. Returns total points written.

    The caller builds `PointStruct` objects; this function only does
    the batching. Vector dimension is assumed correct (Qdrant will
    reject mismatched dims at the first call).
    """
    if not points:
        return 0

    total = 0
    for start in range(0, len(points), batch_size):
        batch = list(points[start : start + batch_size])
        await client.upsert(collection_name=CHUNKS_COLLECTION, points=batch)
        total += len(batch)
        logger.debug("qdrant_bulk_upsert_batch", batch=len(batch), cumulative=total)
    return total


async def delete_chunks_for_doc(client: AsyncQdrantClient, doc_id: str) -> int:
    """Delete all Qdrant points for a document. Returns count deleted."""
    await client.delete(
        collection_name=CHUNKS_COLLECTION,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id",
                        match=qmodels.MatchValue(value=doc_id),
                    )
                ]
            )
        ),
    )
    # qdrant-client returns UpdateResult with operation_id; can't get count directly
    return 0  # Caller should re-query if exact count needed


async def mark_doc_status(
    client: AsyncQdrantClient,
    doc_id: str,
    new_status: str,
) -> int:
    """Update status field on all chunks of a doc (e.g., active -> deprecated)."""
    from qdrant_client.http.exceptions import UnexpectedResponse

    valid = {PayloadStatus.ACTIVE, PayloadStatus.OUTDATED, PayloadStatus.DEPRECATED, PayloadStatus.ARCHIVED, PayloadStatus.DELETED}
    if new_status not in valid:
        raise ValueError(f"Invalid status: {new_status}; must be one of {valid}")

    try:
        await client.update_payload(
            collection_name=CHUNKS_COLLECTION,
            payload={"status": new_status},
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="doc_id",
                            match=qmodels.MatchValue(value=doc_id),
                        )
                    ]
                )
            ),
        )
        return 0  # qdrant-client doesn't return count
    except UnexpectedResponse as e:
        logger.warning("qdrant_mark_status_failed", doc_id=doc_id, error=str(e))
        return 0


__all__ = [
    "BULK_BATCH_SIZE",
    "delete_chunks_for_doc",
    "make_point_id",
    "mark_doc_status",
    "upsert_chunk",
    "upsert_chunks_bulk",
]
