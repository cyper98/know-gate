"""Qdrant collection management (init `chunks` collection with HNSW config)."""

from __future__ import annotations

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import get_settings
from app.vector.client import get_qdrant_client
from app.vector.payload_schema import ChunkPayloadFields

logger = logging.getLogger(__name__)


CHUNKS_COLLECTION = "chunks"
VECTOR_DIM = 1024  # bge-m3 default
HNSW_M = 16
HNSW_EF_CONSTRUCT = 100


async def chunks_collection_exists(client: AsyncQdrantClient) -> bool:
    """Check if `chunks` collection exists."""
    collections = await client.get_collections()
    return any(c.name == CHUNKS_COLLECTION for c in collections.collections)


async def init_chunks_collection(force_recreate: bool = False) -> None:
    """Create `chunks` collection with HNSW config + payload indexes (idempotent).

    - HNSW with m=16, ef_construct=100
    - Payload index on `group_ids` (for fast permission filter)
    - Vector dim: 1024 (bge-m3)
    """
    settings = get_settings()
    client = get_qdrant_client()

    exists = await chunks_collection_exists(client)

    if exists and force_recreate:
        logger.warning("qdrant_dropping_collection", collection=CHUNKS_COLLECTION)
        await client.delete_collection(CHUNKS_COLLECTION)
        exists = False

    if not exists:
        logger.info(
            "qdrant_creating_collection",
            collection=CHUNKS_COLLECTION,
            dim=VECTOR_DIM,
            hnsw_m=HNSW_M,
        )
        await client.create_collection(
            collection_name=CHUNKS_COLLECTION,
            vectors_config=qmodels.VectorParams(
                size=VECTOR_DIM,
                distance=qmodels.Distance.COSINE,
                hnsw_config=qmodels.HnswConfigDiff(
                    m=HNSW_M,
                    ef_construct=HNSW_EF_CONSTRUCT,
                ),
            ),
            # Optimize for write-heavy workload (sync = many upserts)
            optimizers_config=qmodels.OptimizersConfigDiff(
                default_segment_number=2,
                indexing_threshold=20000,
            ),
        )
    else:
        logger.info("qdrant_collection_exists", collection=CHUNKS_COLLECTION)

    # === Payload indexes (for fast filter on group_ids, doc_id, status) ===
    payload_indexes = [
        qmodels.PayloadIndexParams(
            field_name=ChunkPayloadFields.GROUP_IDS,
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        ),
        qmodels.PayloadIndexParams(
            field_name=ChunkPayloadFields.DOC_ID,
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        ),
        qmodels.PayloadIndexParams(
            field_name=ChunkPayloadFields.STATUS,
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        ),
        qmodels.PayloadIndexParams(
            field_name=ChunkPayloadFields.LANGUAGE,
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        ),
        qmodels.PayloadIndexParams(
            field_name=ChunkPayloadFields.SOURCE,
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        ),
    ]

    for idx in payload_indexes:
        field = idx.field_name
        try:
            await client.create_payload_index(
                collection_name=CHUNKS_COLLECTION,
                field_name=field,
                field_schema=idx.field_schema,
            )
            logger.info("qdrant_payload_index_created", field=field)
        except Exception as e:
            # Index may already exist (idempotent) — log debug, continue
            if "already exists" in str(e).lower():
                logger.debug("qdrant_payload_index_exists", field=field)
            else:
                logger.warning("qdrant_payload_index_failed", field=field, error=str(e))


__all__ = ["init_chunks_collection", "chunks_collection_exists", "CHUNKS_COLLECTION"]
