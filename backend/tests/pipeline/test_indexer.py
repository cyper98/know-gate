"""Unit tests for the pipeline orchestrator (`ingest_document`).

Heavy dependencies (Qdrant, MinIO, DB) are mocked. We assert that the
orchestrator runs the correct sequence of steps and updates the
Document row to ACTIVE on success / FAILED on errors.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np


def _fake_document(*, doc_id: str | None = None, status: str = "discovered", object_key: str = "minio-key") -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id or str(uuid.uuid4())
    doc.status = status
    doc.indexed_at = None
    doc.title = "Test Doc"
    doc.mime_type = "text/plain"
    doc.source = "google_drive"
    doc.source_id = "remote-id-1"
    doc.language = None
    doc.extra = {"object_key": object_key}
    doc.error_message = None
    return doc


def _make_session_for_doc(doc: MagicMock) -> MagicMock:
    """Build a session mock that returns `doc` on the first execute and accepts commits."""
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=doc)
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


def test_ingest_document_not_found_returns_skipped() -> None:
    """A non-existent doc_id must return 'skipped' (caller can decide what to do)."""
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    with patch("app.pipeline.indexer.get_session_factory") as mock_factory, \
         patch("app.pipeline.indexer.download_doc", new=AsyncMock()):
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        from app.pipeline.indexer import ingest_document
        result_ingest = None
        import asyncio
        result_ingest = asyncio.run(ingest_document(str(uuid.uuid4())))

    assert result_ingest.status == "skipped"
    assert "not found" in (result_ingest.error or "")


def test_ingest_document_already_active_returns_skipped() -> None:
    """A doc with status=ACTIVE is a no-op (idempotency guard)."""
    doc = _fake_document(status="active")
    doc.indexed_at = datetime.now(UTC)
    session = _make_session_for_doc(doc)

    with patch("app.pipeline.indexer.get_session_factory") as mock_factory:
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        import asyncio

        from app.pipeline.indexer import ingest_document
        r = asyncio.run(ingest_document(str(doc.id)))

    assert r.status == "skipped"
    assert "already" in (r.error or "").lower()


def test_ingest_document_missing_object_key_marks_failed() -> None:
    """A doc row without an `object_key` in extra cannot be downloaded — mark FAILED."""
    doc = _fake_document(object_key="")
    session = _make_session_for_doc(doc)

    with patch("app.pipeline.indexer.get_session_factory") as mock_factory, \
         patch("app.pipeline.indexer._mark_doc_failed", new=AsyncMock()) as mock_failed:
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        import asyncio

        from app.pipeline.indexer import ingest_document
        r = asyncio.run(ingest_document(str(doc.id)))

    assert r.status == "failed"
    assert "object_key" in (r.error or "")
    mock_failed.assert_awaited_once()


def test_ingest_document_happy_path_marks_active() -> None:
    """The end-to-end happy path: parse + chunk + embed + upsert + persist + ACTIVE."""
    from app.pipeline.chunker import Chunk
    from app.pipeline.parser import ParsedDoc, Section

    doc = _fake_document()
    session = _make_session_for_doc(doc)

    fake_parsed = ParsedDoc(
        sections=[Section(title="Intro", level=1, text="Hello world.", page_number=1)]
    )
    fake_chunks = [
        Chunk(text="Hello world.", section_title="Intro", chunk_index=0, token_count=2, page_number=1)
    ]
    fake_vectors = np.array([[0.1] * 1024, [0.2] * 1024], dtype=np.float32)

    with patch("app.pipeline.indexer.get_session_factory") as mock_factory, \
         patch("app.pipeline.indexer.download_doc", new=AsyncMock(return_value=b"raw-bytes")), \
         patch("app.pipeline.indexer.parse_bytes", return_value=fake_parsed), \
         patch("app.pipeline.indexer.chunk_by_sections", return_value=fake_chunks), \
         patch("app.pipeline.indexer.embed_batch", return_value=fake_vectors[:1]), \
         patch("app.pipeline.indexer.model_version", return_value="bge-m3-v1.0.0"), \
         patch("app.pipeline.indexer.embed_dim", return_value=1024), \
         patch("app.pipeline.indexer.get_qdrant_client") as mock_qclient, \
         patch("app.pipeline.indexer.upsert_chunks_bulk", new=AsyncMock(return_value=1)) as mock_upsert, \
         patch("app.pipeline.indexer._get_group_ids", new=AsyncMock(return_value=["grp-1"])), \
         patch("app.pipeline.indexer._persist_chunks", new=AsyncMock()) as mock_persist, \
         patch("app.pipeline.indexer._mark_doc_active", new=AsyncMock()) as mock_active:
        mock_qclient.return_value = MagicMock()
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        import asyncio

        from app.pipeline.indexer import ingest_document
        r = asyncio.run(ingest_document(str(doc.id)))

    assert r.status == "active"
    assert r.chunk_count == 1
    mock_upsert.assert_awaited_once()
    mock_persist.assert_awaited_once()
    mock_active.assert_awaited_once_with(
        str(doc.id), chunk_count=1, embedding_model="bge-m3-v1.0.0"
    )


def test_ingest_document_empty_document_marks_failed() -> None:
    """A PDF with no text layer must NOT crash — mark FAILED and return."""
    from app.pipeline.parser import EmptyDocumentError

    doc = _fake_document()
    session = _make_session_for_doc(doc)

    with patch("app.pipeline.indexer.get_session_factory") as mock_factory, \
         patch("app.pipeline.indexer.download_doc", new=AsyncMock(return_value=b"")), \
         patch("app.pipeline.indexer.parse_bytes", side_effect=EmptyDocumentError("no text layer")), \
         patch("app.pipeline.indexer._mark_doc_failed", new=AsyncMock()) as mock_failed:
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        import asyncio

        from app.pipeline.indexer import ingest_document
        r = asyncio.run(ingest_document(str(doc.id)))

    assert r.status == "failed"
    assert "text layer" in (r.error or "")
    mock_failed.assert_awaited_once()


def test_ingest_document_qdrant_failure_marks_failed() -> None:
    """Qdrant outage during upsert → mark FAILED, no orphan chunks persisted."""
    from app.pipeline.chunker import Chunk
    from app.pipeline.parser import ParsedDoc, Section

    doc = _fake_document()
    session = _make_session_for_doc(doc)
    fake_parsed = ParsedDoc(sections=[Section(title="A", level=1, text="body", page_number=1)])
    fake_chunks = [Chunk(text="body", section_title="A", chunk_index=0, token_count=1, page_number=1)]
    fake_vectors = np.zeros((1, 1024), dtype=np.float32)

    with patch("app.pipeline.indexer.get_session_factory") as mock_factory, \
         patch("app.pipeline.indexer.download_doc", new=AsyncMock(return_value=b"x")), \
         patch("app.pipeline.indexer.parse_bytes", return_value=fake_parsed), \
         patch("app.pipeline.indexer.chunk_by_sections", return_value=fake_chunks), \
         patch("app.pipeline.indexer.embed_batch", return_value=fake_vectors), \
         patch("app.pipeline.indexer.model_version", return_value="bge-m3-v1.0.0"), \
         patch("app.pipeline.indexer.embed_dim", return_value=1024), \
         patch("app.pipeline.indexer.get_qdrant_client"), \
         patch("app.pipeline.indexer.upsert_chunks_bulk", new=AsyncMock(side_effect=RuntimeError("qdrant down"))), \
         patch("app.pipeline.indexer._get_group_ids", new=AsyncMock(return_value=[])), \
         patch("app.pipeline.indexer._persist_chunks", new=AsyncMock()) as mock_persist, \
         patch("app.pipeline.indexer._mark_doc_failed", new=AsyncMock()) as mock_failed:
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        import asyncio

        from app.pipeline.indexer import ingest_document
        r = asyncio.run(ingest_document(str(doc.id)))

    assert r.status == "failed"
    assert "qdrant" in (r.error or "").lower()
    # _persist_chunks must NOT be called when Qdrant fails
    mock_persist.assert_not_awaited()
    mock_failed.assert_awaited_once()
