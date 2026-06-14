"""Sync engine — orchestrates a single sync run for one Source.

Flow:
1. Load Source row from DB
2. Decrypt config
3. Instantiate the right connector
4. Validate credentials (skip + mark AUTH_FAILED on auth error)
5. list_changes(cursor) — discover new/updated/deleted docs
6. For each doc: fetch → upload to MinIO → upsert Document row → emit progress
7. Persist next cursor on Source row
8. Mark SyncJob COMPLETED (or PARTIAL if any doc failed)

This is the workhorse; the Celery task is a thin wrapper.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.crypto.aes import decrypt_str
from app.db.enums import DocumentStatus, SourceType, SyncJobStatus
from app.db.models import Document, Source, SyncJob
from app.db.models.source import Source as SourceModel
from app.db.session import get_session_factory
from app.logging import get_logger
from app.sources.base import (
    BaseSourceConnector,
    ConnectorAuthError,
    ConnectorError,
    ConnectorRateLimitError,
)
from app.sources.google_drive import GoogleDriveConnector
from app.sources.google_drive import deserialize_config as drive_deserialize
from app.sources.notion import NotionConnector
from app.sources.notion import deserialize_config as notion_deserialize
from app.sources.progress import publish_event
from app.storage.uploader import upload_doc

logger = get_logger(__name__)

# Hard cap per the spec: warn on docs larger than this (and skip)
def _max_doc_size_bytes() -> int:
    return get_settings().max_doc_size_mb * 1024 * 1024


# === Connector factory ===

def build_connector(source: SourceModel) -> BaseSourceConnector:
    """Instantiate the right connector for a Source row, with config decrypted."""
    settings = get_settings()
    key = settings.kg_encryption_key.get_secret_value()
    plain_config = decrypt_str(source.config_encrypted, key)
    cfg = _deserialize(source.type, plain_config)

    if source.type == SourceType.GOOGLE_DRIVE.value:
        return GoogleDriveConnector(str(source.id), cfg)
    if source.type == SourceType.NOTION.value:
        return NotionConnector(str(source.id), cfg)
    raise ConnectorError(f"Unknown source type: {source.type}")


def _deserialize(source_type: str, blob: str) -> dict[str, Any]:
    if source_type == SourceType.GOOGLE_DRIVE.value:
        return drive_deserialize(blob)
    if source_type == SourceType.NOTION.value:
        return notion_deserialize(blob)
    raise ConnectorError(f"Unknown source type: {source_type}")


# === Sync run ===

async def run_sync(
    *,
    source_id: str,
    job_id: str,
    triggered_by: str = "manual",
) -> None:
    """Execute a full sync for one Source. Idempotent and resumable per batch.

    `job_id` is the SyncJob row ID. Caller (Celery task or admin API) is
    responsible for creating that row before calling `run_sync`.
    """
    factory = get_session_factory()
    # 1. Load source
    async with factory() as session:
        src_result = await session.execute(select(Source).where(Source.id == source_id))
        source = src_result.scalar_one_or_none()
        if source is None:
            logger.error("sync_source_not_found", source_id=source_id)
            await _finalize_job(job_id, SyncJobStatus.FAILED.value, "source not found")
            return
        cursor = source.sync_cursor
        # Decrypt once, attach to row in-memory (we don't persist plaintext)
        try:
            connector = build_connector(source)
        except Exception as e:
            logger.exception("sync_connector_build_failed", source_id=source_id)
            await _finalize_job(job_id, SyncJobStatus.FAILED.value, str(e))
            return

    # 2. Validate credentials
    try:
        await connector.validate_credentials()
    except ConnectorAuthError as e:
        await _mark_source_status(source_id, "auth_failed", str(e))
        await _finalize_job(job_id, SyncJobStatus.FAILED.value, f"auth failed: {e}")
        return
    except Exception as e:
        logger.exception("sync_validate_failed", source_id=source_id)
        await _finalize_job(job_id, SyncJobStatus.FAILED.value, str(e))
        return

    # 3. List changes
    try:
        docs, next_cursor = await connector.list_changes(cursor)
    except ConnectorAuthError as e:
        await _mark_source_status(source_id, "auth_failed", str(e))
        await _finalize_job(job_id, SyncJobStatus.FAILED.value, f"auth failed: {e}")
        return
    except ConnectorRateLimitError as e:
        # Don't fail the job; let it retry on the next scheduler tick
        await _finalize_job(job_id, SyncJobStatus.QUEUED.value, f"rate limit: {e}")
        return
    except Exception as e:
        logger.exception("sync_list_changes_failed", source_id=source_id)
        await _finalize_job(job_id, SyncJobStatus.FAILED.value, str(e))
        return

    total = len(docs)
    failed = 0
    error_log: dict[str, Any] = {}
    await _set_job_total(job_id, total)
    await publish_event(job_id, stage="start", current=0, total=total, failed=0,
                        message=f"discovered {total} docs")

    # 4. Process each doc
    for idx, doc in enumerate(docs, start=1):
        if doc.is_deleted:
            # Mark Document row as DELETED (or just upsert the tombstone)
            await _mark_doc_deleted(source.type, doc.id)
            await publish_event(job_id, stage="delete", current=idx, total=total,
                                failed=failed, message=f"deleted {doc.id}", doc_id=doc.id)
            continue
        try:
            if doc.size_bytes and doc.size_bytes > _max_doc_size_bytes():
                msg = f"doc {doc.id} exceeds max size ({doc.size_bytes} bytes); skipped"
                logger.warning("sync_doc_too_large", source_id=source_id, doc_id=doc.id,
                               size=doc.size_bytes)
                error_log[doc.id] = msg
                failed += 1
                await publish_event(job_id, stage="skip", current=idx, total=total,
                                    failed=failed, message=msg, doc_id=doc.id)
                continue
            raw, current = await connector.fetch_doc(doc.id)
            # Upload to MinIO under a namespaced key
            key = f"{source.type}/{source.id}/{doc.id}"
            await upload_doc(key, raw, content_type=current.mime_type or "application/octet-stream")
            # Upsert Document row (returns the row id so we can enqueue ingest)
            doc_row_id = await _upsert_document(
                source_type=source.type,
                source_row_id=source.id,
                doc=current,
                object_key=key,
            )
            # Enqueue ingestion (parse + chunk + embed + index) for the worker.
            # Done AFTER the Document row is committed so the worker can
            # find it. Eager mode (tests) runs the task synchronously, but
            # we still call .delay() so the contract is identical.
            if doc_row_id:
                try:
                    from app.tasks.ingest import ingest_doc_task
                    ingest_doc_task.delay(doc_row_id)
                except Exception as e:
                    # Broker outage should not fail the sync — the Document
                    # row is in DISCOVERED and the next scheduled sync
                    # (or an admin retry) will re-enqueue.
                    logger.warning("sync_enqueue_ingest_failed", doc_id=doc_row_id, error=str(e))
            await publish_event(job_id, stage="fetch", current=idx, total=total,
                                failed=failed, message=f"fetched {doc.title!r}",
                                doc_id=doc.id)
        except Exception as e:
            logger.exception("sync_doc_failed", source_id=source_id, doc_id=doc.id)
            error_log[doc.id] = str(e)[:500]
            failed += 1
            await publish_event(job_id, stage="failed", current=idx, total=total,
                                failed=failed, message=str(e)[:200], doc_id=doc.id)

    # 5. Persist cursor + finalize
    await _set_source_cursor(source_id, next_cursor)
    final_status = (
        SyncJobStatus.COMPLETED.value if failed == 0
        else (SyncJobStatus.PARTIAL.value if (total - failed) > 0
              else SyncJobStatus.FAILED.value)
    )
    await _finalize_job(job_id, final_status, error_summary=error_log,
                        indexed=total - failed, failed=failed)
    await _mark_source_last_sync(source_id, last_error=error_log if failed else None)
    await publish_event(job_id, stage="complete", current=total, total=total,
                        failed=failed, message=f"done ({final_status})")
    # Best-effort close — never break the job over a connection close failure
    import contextlib
    with contextlib.suppress(Exception):
        await connector.aclose()


# === DB helpers (small + private) ===

async def _set_job_total(job_id: str, total: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            select(SyncJob).where(SyncJob.id == job_id)  # warm cache
        )
        job = (await session.execute(select(SyncJob).where(SyncJob.id == job_id))).scalar_one()
        job.total_docs = total
        await session.commit()


async def _finalize_job(
    job_id: str,
    status: str,
    error_summary: str | dict[str, Any] | None = None,
    indexed: int = 0,
    failed: int = 0,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        job = (await session.execute(select(SyncJob).where(SyncJob.id == job_id))).scalar_one()
        job.status = status
        job.indexed_docs = indexed
        job.failed_docs = failed
        if isinstance(error_summary, dict) and error_summary:
            existing = dict(job.error_log or {})
            existing.update(error_summary)
            job.error_log = existing
        elif isinstance(error_summary, str) and error_summary:
            existing = dict(job.error_log or {})
            existing["_summary"] = error_summary
            job.error_log = existing
        job.completed_at = datetime.now(UTC)
        await session.commit()


async def _mark_source_status(source_id: str, status: str, last_error: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        src = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one()
        src.status = status
        src.last_error = last_error[:1000]
        await session.commit()


async def _set_source_cursor(source_id: str, cursor: str | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        src = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one()
        src.sync_cursor = cursor
        await session.commit()


async def _mark_source_last_sync(source_id: str, last_error: dict[str, Any] | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        src = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one()
        src.last_sync_at = datetime.now(UTC)
        if last_error:
            src.last_error = str(last_error)[:1000]
        elif src.status == "auth_failed":
            pass  # keep the auth error
        else:
            src.last_error = None
        await session.commit()


async def _upsert_document(
    *,
    source_type: str,
    source_row_id: str,
    doc,  # SourceDoc
    object_key: str,
) -> str | None:
    """Upsert a Document row by (source, source_id) — see unique constraint.

    Returns the Document row id (as a string) so the caller can enqueue
    the ingestion task. Returns None only on an unexpected DB error.
    """
    factory = get_session_factory()
    async with factory() as session:
        values = {
            "source": source_type,
            "source_id": doc.id,
            "source_url": doc.url,
            "source_modified_at": doc.modified_at,
            "title": doc.title,
            "mime_type": doc.mime_type,
            "size_bytes": doc.size_bytes,
            "status": DocumentStatus.DISCOVERED.value,
            "extra": {**(doc.extra or {}), "object_key": object_key},
            "content_hash": None,
        }
        stmt = pg_insert(Document).values(**values)
        # On conflict, update metadata if the source timestamp is newer
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "source_id"],
            set_={
                "source_url": stmt.excluded.source_url,
                "source_modified_at": stmt.excluded.source_modified_at,
                "title": stmt.excluded.title,
                "mime_type": stmt.excluded.mime_type,
                "size_bytes": stmt.excluded.size_bytes,
                "status": DocumentStatus.DISCOVERED.value,
                "extra": stmt.excluded.extra,
                "updated_at": datetime.now(UTC),
            },
        )
        await session.execute(stmt)
        await session.commit()

        # Re-read to get the row id (RETURNING is not supported in the
        # upsert above because the row may have existed pre-conflict).
        existing = await session.execute(
            select(Document).where(
                Document.source == source_type, Document.source_id == doc.id
            )
        )
        row = existing.scalar_one_or_none()
        return str(row.id) if row is not None else None


async def _mark_doc_deleted(source_type: str, provider_doc_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        existing = await session.execute(
            select(Document).where(
                Document.source == source_type, Document.source_id == provider_doc_id
            )
        )
        doc = existing.scalar_one_or_none()
        if doc is None:
            return  # never seen this doc; nothing to delete
        doc.status = DocumentStatus.DELETED.value
        await session.commit()
