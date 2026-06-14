"""Pipeline orchestrator (parse + chunk + embed + index + persist).

`ingest_document(doc_id)` is the end-to-end entrypoint. It runs all
the steps in this order:

    1. Load Document row from PG (status must be DISCOVERED / OUTDATED)
    2. Download raw bytes from MinIO (the sync engine stored the file
       there during the source sync)
    3. Parse with the Unstructured-backed parser
    4. Chunk the parsed sections (heading-aware + recursive fallback)
    5. Detect language per chunk (vi / en / zh / und)
    6. Embed the chunks with bge-m3 (batched, normalized)
    7. Upsert points to Qdrant (bulk, 500/batch)
    8. Insert / upsert Chunk rows in PG with `qdrant_point_id`,
       `embedding_model`, `embedding_dim`, `language`
    9. Mark Document.status = ACTIVE and set `indexed_at`

Failure handling:
- Empty document (scanned PDF) -> Document.status = FAILED,
  error_message = "no text layer"
- Parse error -> same, error_message = str(exc)
- Embedder / Qdrant error -> propagate up to the Celery task so the
  task can retry. The PG / Qdrant state is left consistent (a failed
  doc has no orphan chunks because the chunk insert is the last step
  before status update).
- Idempotency: re-running on the same document overwrites the same
  Qdrant point IDs (deterministic UUID v5) and PG unique constraint
  on (document_id, chunk_index) makes the Chunk upsert safe.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.enums import DocumentStatus
from app.db.models import Chunk, Document
from app.db.session import get_session_factory
from app.logging import get_logger
from app.pipeline.chunker import Chunk as ParsedChunk
from app.pipeline.chunker import chunk_by_sections
from app.pipeline.embedder import embed_batch, embed_dim, model_version
from app.pipeline.lang_detect import detect_language
from app.pipeline.parser import EmptyDocumentError, ParsedDoc, ParserError, parse_bytes
from app.storage.uploader import download_doc
from app.vector.client import get_qdrant_client
from app.vector.indexer import make_point_id, upsert_chunks_bulk
from app.vector.payload_schema import PayloadStatus

logger = get_logger(__name__)


# === Public API ===

@dataclass(slots=True)
class IngestResult:
    """Summary of a single ingest run — useful for tests + ops dashboards."""

    doc_id: str
    status: str  # "active" | "failed" | "skipped"
    chunk_count: int = 0
    error: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None


async def ingest_document(doc_id: str) -> IngestResult:
    """End-to-end ingest for one Document row.

    Returns an `IngestResult` describing the outcome. The caller (Celery
    task) is responsible for catching exceptions; we re-raise parser /
    embed / qdrant errors so the task can decide on retry.
    """
    logger.info("ingest_start", doc_id=doc_id)
    factory = get_session_factory()

    # 1. Load the document
    async with factory() as session:
        result = await session.execute(select(Document).where(Document.id == doc_id))
        doc: Document | None = result.scalar_one_or_none()
        if doc is None:
            logger.warning("ingest_doc_not_found", doc_id=doc_id)
            return IngestResult(doc_id=doc_id, status="skipped", error="document not found")

        # Idempotency: a doc already ACTIVE with the same model version
        # is a no-op. Re-embed is handled by the reembed task.
        if doc.status == DocumentStatus.ACTIVE.value and doc.indexed_at is not None:
            logger.info("ingest_skip_active", doc_id=doc_id)
            return IngestResult(doc_id=doc_id, status="skipped", error="already active")

        object_key = (doc.extra or {}).get("object_key")
        if not object_key:
            logger.error("ingest_no_object_key", doc_id=doc_id)
            await _mark_doc_failed(doc_id, "missing object_key in doc.extra")
            return IngestResult(doc_id=doc_id, status="failed", error="missing object_key")

        # Mark as INDEXING so the API and admin UI reflect progress
        doc.status = DocumentStatus.INDEXING.value
        await session.commit()

        mime_type = doc.mime_type or "application/octet-stream"
        title = doc.title
        source = doc.source
        source_id_value = doc.source_id

    try:
        # 2. Download from MinIO
        raw = await download_doc(object_key)
    except Exception as e:
        logger.exception("ingest_download_failed", doc_id=doc_id)
        await _mark_doc_failed(doc_id, f"download failed: {e}"[:500])
        return IngestResult(doc_id=doc_id, status="failed", error=f"download: {e}")

    # 3. Parse
    try:
        parsed: ParsedDoc = parse_bytes(raw, mime_type=mime_type, filename=object_key)
    except EmptyDocumentError as e:
        logger.warning("ingest_empty_document", doc_id=doc_id, error=str(e))
        await _mark_doc_failed(doc_id, "no text layer (scanned PDF?)")
        return IngestResult(doc_id=doc_id, status="failed", error=str(e))
    except ParserError as e:
        logger.exception("ingest_parse_failed", doc_id=doc_id)
        await _mark_doc_failed(doc_id, f"parse error: {e}"[:500])
        return IngestResult(doc_id=doc_id, status="failed", error=f"parse: {e}")

    # 4. Chunk
    chunks = chunk_by_sections(parsed)
    if not chunks:
        logger.warning("ingest_no_chunks", doc_id=doc_id, title=title)
        await _mark_doc_failed(doc_id, "parser produced no chunks")
        return IngestResult(doc_id=doc_id, status="failed", error="no chunks")

    # 5. Detect language per chunk (cheap; langdetect is in-memory)
    texts = [c.text for c in chunks]
    languages = [detect_language(t) for t in texts]

    # 6. Embed (sync, CPU-bound — run in thread to keep event loop free)
    import asyncio
    try:
        vectors = await asyncio.to_thread(embed_batch, texts)
    except Exception as e:
        logger.exception("ingest_embed_failed", doc_id=doc_id)
        await _mark_doc_failed(doc_id, f"embed error: {e}"[:500])
        return IngestResult(doc_id=doc_id, status="failed", error=f"embed: {e}")

    if vectors.shape[0] != len(chunks):
        # Sanity check (should be impossible if embed_batch behaves)
        await _mark_doc_failed(doc_id, f"vector count mismatch ({vectors.shape[0]} vs {len(chunks)})")
        return IngestResult(
            doc_id=doc_id, status="failed", error="vector count mismatch"
        )

    # 7. Build Qdrant payload + upsert
    emb_model = model_version()
    emb_dim = embed_dim()
    indexed_at = datetime.now(UTC).isoformat()

    # Collect group_ids from the doc's M:N relation
    group_ids = await _get_group_ids(doc_id)

    from qdrant_client.http import models as qmodels
    points = [
        qmodels.PointStruct(
            id=make_point_id(doc_id, c.chunk_index),
            vector=vectors[i].tolist(),
            payload={
                "chunk_id": None,  # filled after we know the PG row id
                "doc_id": doc_id,
                "group_ids": group_ids,
                "language": languages[i],
                "status": PayloadStatus.ACTIVE,
                "chunk_index": c.chunk_index,
                "section_title": c.section_title,
                "indexed_at": indexed_at,
                "source": source,
                "source_id": source_id_value,
            },
        )
        for i, c in enumerate(chunks)
    ]

    try:
        client = get_qdrant_client()
        written = await upsert_chunks_bulk(client, points)
        logger.info("ingest_qdrant_upserted", doc_id=doc_id, points=written)
    except Exception as e:
        logger.exception("ingest_qdrant_failed", doc_id=doc_id)
        await _mark_doc_failed(doc_id, f"qdrant error: {e}"[:500])
        return IngestResult(doc_id=doc_id, status="failed", error=f"qdrant: {e}")

    # 8. Persist Chunk rows in PG (upsert by (document_id, chunk_index))
    await _persist_chunks(
        doc_id=doc_id,
        chunks=chunks,
        languages=languages,
        embedding_model=emb_model,
        embedding_dim=emb_dim,
    )

    # 9. Mark doc ACTIVE
    await _mark_doc_active(doc_id, chunk_count=len(chunks), embedding_model=emb_model)

    logger.info(
        "ingest_done",
        doc_id=doc_id,
        chunks=len(chunks),
        embedding_model=emb_model,
    )
    return IngestResult(
        doc_id=doc_id,
        status=DocumentStatus.ACTIVE.value,
        chunk_count=len(chunks),
        embedding_model=emb_model,
        embedding_dim=emb_dim,
    )


# === DB helpers ===

async def _get_group_ids(doc_id: str) -> list[str]:
    """Return access-group UUIDs (as strings) the document belongs to.

    Used for the Qdrant payload's `group_ids` filter field (so the
    read path can intersect with the user's group membership).
    """
    factory = get_session_factory()
    async with factory() as session:
        # Pull group_ids from the M:N table
        from sqlalchemy import text
        rows = await session.execute(
            text("SELECT group_id::text FROM document_groups WHERE document_id = :d"),
            {"d": doc_id},
        )
        return [r[0] for r in rows.all()]


async def _persist_chunks(
    *,
    doc_id: str,
    chunks: Sequence[ParsedChunk],
    languages: Sequence[str],
    embedding_model: str,
    embedding_dim: int,
) -> None:
    """Upsert Chunk rows in PG by (document_id, chunk_index)."""
    factory = get_session_factory()
    async with factory() as session:
        # Pre-compute Qdrant point ids (deterministic)
        point_ids = {c.chunk_index: make_point_id(doc_id, c.chunk_index) for c in chunks}

        for c, lang in zip(chunks, languages, strict=True):
            values = {
                "document_id": doc_id,
                "section_title": c.section_title,
                "chunk_text": c.text,
                "token_count": c.token_count,
                "page_number": c.page_number,
                "language": lang,
                "chunk_index": c.chunk_index,
                "qdrant_point_id": point_ids[c.chunk_index],
                "embedding_model": embedding_model,
                "embedding_dim": embedding_dim,
            }
            stmt = pg_insert(Chunk).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["document_id", "chunk_index"],
                set_={
                    "section_title": stmt.excluded.section_title,
                    "chunk_text": stmt.excluded.chunk_text,
                    "token_count": stmt.excluded.token_count,
                    "page_number": stmt.excluded.page_number,
                    "language": stmt.excluded.language,
                    "qdrant_point_id": stmt.excluded.qdrant_point_id,
                    "embedding_model": stmt.excluded.embedding_model,
                    "embedding_dim": stmt.excluded.embedding_dim,
                },
            )
            await session.execute(stmt)
        await session.commit()


async def _mark_doc_active(
    doc_id: str, *, chunk_count: int, embedding_model: str
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        doc = (
            await session.execute(select(Document).where(Document.id == doc_id))
        ).scalar_one()
        doc.status = DocumentStatus.ACTIVE.value
        doc.indexed_at = datetime.now(UTC)
        doc.error_message = None
        # Stash chunk count + model in extra for ops visibility
        extra = dict(doc.extra or {})
        extra["chunk_count"] = chunk_count
        extra["embedding_model"] = embedding_model
        doc.extra = extra
        await session.commit()


async def _mark_doc_failed(doc_id: str, error: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        doc = (
            await session.execute(select(Document).where(Document.id == doc_id))
        ).scalar_one()
        doc.status = DocumentStatus.FAILED.value
        doc.error_message = error[:1000]
        await session.commit()


__all__ = ["IngestResult", "ingest_document"]
