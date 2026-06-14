"""Vector store package (Qdrant)."""

from app.vector.client import check_qdrant, close_qdrant, get_qdrant_client
from app.vector.collections import CHUNKS_COLLECTION, init_chunks_collection
from app.vector.indexer import delete_chunks_for_doc, mark_doc_status, upsert_chunk
from app.vector.payload_schema import ChunkPayload, ChunkPayloadFields, PayloadStatus

__all__ = [
    "check_qdrant",
    "close_qdrant",
    "get_qdrant_client",
    "init_chunks_collection",
    "CHUNKS_COLLECTION",
    "delete_chunks_for_doc",
    "mark_doc_status",
    "upsert_chunk",
    "ChunkPayload",
    "ChunkPayloadFields",
    "PayloadStatus",
]
