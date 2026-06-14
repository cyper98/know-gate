"""Vector store package (Qdrant)."""

from app.vector.client import check_qdrant, close_qdrant, get_qdrant_client
from app.vector.collections import CHUNKS_COLLECTION, init_chunks_collection
from app.vector.indexer import (
    BULK_BATCH_SIZE,
    delete_chunks_for_doc,
    make_point_id,
    mark_doc_status,
    upsert_chunk,
    upsert_chunks_bulk,
)
from app.vector.payload_schema import ChunkPayload, ChunkPayloadFields, PayloadStatus

__all__ = [
    "BULK_BATCH_SIZE",
    "CHUNKS_COLLECTION",
    "ChunkPayload",
    "ChunkPayloadFields",
    "PayloadStatus",
    "check_qdrant",
    "close_qdrant",
    "delete_chunks_for_doc",
    "get_qdrant_client",
    "init_chunks_collection",
    "make_point_id",
    "mark_doc_status",
    "upsert_chunk",
    "upsert_chunks_bulk",
]
