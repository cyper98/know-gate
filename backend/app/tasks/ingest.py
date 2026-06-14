"""Celery tasks for the ingestion pipeline.

- `ingest_doc_task(doc_id)` — end-to-end ingest for one document.
  Called by the sync engine after a successful source upload, and by
  the admin "retry failed doc" endpoint.

- `reembed_all_task(model_version)` — sweep all chunks and re-embed
  with a new model version. Used when the embedding model is upgraded
  (e.g., bge-m3 v1.0 -> v1.1). Batched in chunks of `reembed_batch`
  to bound memory.

- `reembed_one_task(chunk_id)` — re-embed a single chunk (admin debug).

The worker pre-warms the bge-m3 model on startup (see the
`worker_init` signal handler at the bottom of this file) so the first
real request after boot does not pay a 5+ second model load.
"""

from __future__ import annotations

import asyncio

from celery.signals import worker_init
from sqlalchemy import select

from app.celery_app import celery_app
from app.db.models import Chunk
from app.db.session import get_session_factory
from app.logging import get_logger
from app.pipeline.embedder import prewarm_embedder
from app.pipeline.indexer import ingest_document
from app.vector.client import get_qdrant_client
from app.vector.indexer import make_point_id, upsert_chunks_bulk

logger = get_logger(__name__)

# How many chunks to re-embed per batch in `reembed_all_task`.
# Bound memory: each bge-m3 vector is 4KB, plus the input text. 256
# chunks = ~10MB peak working set on top of the model itself.
REEMBED_BATCH_SIZE = 256


# === Tasks ===

@celery_app.task(
    name="ingest_doc",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def ingest_doc_task(self, doc_id: str) -> dict:
    """Ingest one document end-to-end.

    Returns a small dict with the outcome (status + chunk_count) so
    callers (e.g., admin retry endpoint) can verify without a DB read.

    Retries: 3 with 60s delay on transient errors. Auth / config errors
    are NOT retried.
    """
    logger.info("ingest_task_start", doc_id=doc_id)
    try:
        result = asyncio.run(ingest_document(doc_id))
    except Exception as e:
        logger.exception("ingest_task_crashed", doc_id=doc_id, error=str(e))
        # Don't retry "document not found" / "already active"
        msg = str(e).lower()
        if "not found" in msg or "already" in msg:
            return {"doc_id": doc_id, "status": "skipped", "error": str(e)[:200]}
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            return {"doc_id": doc_id, "status": "failed", "error": str(e)[:500]}
    logger.info("ingest_task_done", doc_id=doc_id, status=result.status, chunks=result.chunk_count)
    return {
        "doc_id": doc_id,
        "status": result.status,
        "chunk_count": result.chunk_count,
        "error": result.error,
    }


@celery_app.task(
    name="reembed_all",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def reembed_all_task(self, model_version: str | None = None) -> dict:
    """Re-embed all chunks with the current model version.

    The current model version is taken from the embedder unless an
    explicit `model_version` is passed (useful for rollback to a
    previous version).
    """
    from app.pipeline.embedder import embed_batch, embed_dim
    from app.pipeline.embedder import model_version as current_version

    target_version = model_version or current_version()
    logger.info("reembed_all_start", target_version=target_version, batch_size=REEMBED_BATCH_SIZE)

    factory = get_session_factory()

    async def _run() -> dict:
        # Gather all chunk ids in the DB
        async with factory() as session:
            rows = await session.execute(select(Chunk.id, Chunk.chunk_text, Chunk.document_id, Chunk.chunk_index))
            all_chunks = rows.all()
        total = len(all_chunks)
        if total == 0:
            return {"total": 0, "upserted": 0, "model_version": target_version}

        from qdrant_client.http import models as qmodels

        upserted = 0
        for start in range(0, total, REEMBED_BATCH_SIZE):
            batch = all_chunks[start : start + REEMBED_BATCH_SIZE]
            texts = [row.chunk_text for row in batch]
            vectors = await asyncio.to_thread(embed_batch, texts)
            points = [
                qmodels.PointStruct(
                    id=make_point_id(str(row.document_id), row.chunk_index),
                    vector=vectors[i].tolist(),
                    payload={
                        "chunk_id": str(row.id),
                        "doc_id": str(row.document_id),
                        "group_ids": [],
                        "language": None,
                        "status": "active",
                        "chunk_index": row.chunk_index,
                        "section_title": None,
                        "indexed_at": None,
                        "source": None,
                        "source_id": None,
                    },
                )
                for i, row in enumerate(batch)
            ]
            client = get_qdrant_client()
            written = await upsert_chunks_bulk(client, points)
            upserted += written
            logger.info(
                "reembed_batch_done",
                batch=start // REEMBED_BATCH_SIZE + 1,
                batch_count=len(batch),
                cumulative=upserted,
            )

        # Update embedding_model on all chunks (PG metadata)
        async with factory() as session:
            chunks_rows = (
                await session.execute(select(Chunk))
            ).scalars().all()
            for c in chunks_rows:
                c.embedding_model = target_version
                c.embedding_dim = embed_dim()
            await session.commit()

        return {"total": total, "upserted": upserted, "model_version": target_version}

    try:
        return asyncio.run(_run())
    except Exception as e:
        logger.exception("reembed_all_crashed", error=str(e))
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            return {"total": 0, "upserted": 0, "error": str(e)[:500]}


@celery_app.task(name="reembed_one")
def reembed_one_task(chunk_id: str) -> dict:
    """Re-embed a single chunk (admin debug)."""
    from app.pipeline.embedder import embed_batch, model_version

    async def _run() -> dict:
        factory = get_session_factory()
        async with factory() as session:
            chunk = (
                await session.execute(select(Chunk).where(Chunk.id == chunk_id))
            ).scalar_one_or_none()
            if chunk is None:
                return {"chunk_id": chunk_id, "status": "not_found"}
            text = chunk.chunk_text
            doc_id = str(chunk.document_id)
            chunk_index = chunk.chunk_index

        vectors = await asyncio.to_thread(embed_batch, [text])
        from qdrant_client.http import models as qmodels
        point = qmodels.PointStruct(
            id=make_point_id(doc_id, chunk_index),
            vector=vectors[0].tolist(),
            payload={
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "group_ids": [],
                "language": None,
                "status": "active",
                "chunk_index": chunk_index,
                "section_title": None,
                "indexed_at": None,
                "source": None,
                "source_id": None,
            },
        )
        client = get_qdrant_client()
        await upsert_chunks_bulk(client, [point])
        return {"chunk_id": chunk_id, "status": "ok", "model_version": model_version()}

    return asyncio.run(_run())


# === Worker startup hook ===

def prewarm() -> None:
    """Load the bge-m3 model into memory.

    Call this from the Celery worker process once, ideally from a
    `worker_init` signal handler. Safe to call multiple times (the
    embedder is a lazy singleton).
    """
    try:
        prewarm_embedder()
    except Exception as e:
        # Don't crash the worker on a model-load failure — the task
        # will surface the error and the operator can fix it.
        logger.error("ingest_worker_prewarm_failed", error=str(e))


@worker_init.connect
def _on_worker_init(**_kwargs) -> None:
    """Celery signal: pre-warm the embedder in every worker process.

    This runs once per worker (before any task is picked up). If the
    model fails to load we log and continue — the first ingest task
    will surface the error and the operator can debug.
    """
    logger.info("ingest_worker_init_prewarm")
    prewarm()


__all__ = [
    "REEMBED_BATCH_SIZE",
    "ingest_doc_task",
    "prewarm",
    "reembed_all_task",
    "reembed_one_task",
]
