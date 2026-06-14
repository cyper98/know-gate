"""Unit tests for the sync engine (mocked connector + DB + storage)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.sources.base import SourceDoc
from app.sources.sync import run_sync

# === Test helpers ===

def _make_source_doc(
    doc_id: str = "doc-1",
    title: str = "Doc 1",
    size: int | None = 1024,
    deleted: bool = False,
) -> SourceDoc:
    return SourceDoc(
        id=doc_id,
        title=title,
        mime_type="application/pdf",
        modified_at=datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
        url="https://example.com/" + doc_id,
        size_bytes=size,
        is_deleted=deleted,
    )


def _fake_source(*, source_id: str | None = None, type_: str = "google_drive") -> MagicMock:
    src = MagicMock()
    src.id = source_id or str(uuid.uuid4())
    src.type = type_
    src.config_encrypted = "encrypted-blob"
    src.sync_cursor = None
    src.status = "active"
    return src


def _fake_session_with_source(source: MagicMock | None) -> AsyncMock:
    """Return a session-like async context manager that yields a Source on the
    first .execute() and a SyncJob on the second (for the `_set_job_total` call)."""
    # We don't model the full SQLAlchemy session — we patch at a higher level
    # (factory + get_session_factory) so the engine never touches real DB.
    return AsyncMock()


def _make_session_with_source(source: MagicMock) -> MagicMock:
    """Build a session mock where `execute()` returns a result that has
    `scalar_one_or_none()` returning `source`. This is enough to satisfy the
    sync engine's first DB read; all subsequent DB calls are explicitly
    patched in the tests."""
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=source)
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


# === Happy path ===

@pytest.mark.asyncio
async def test_run_sync_happy_path_completes_and_saves_cursor() -> None:
    """End-to-end mock: list 2 docs, fetch + upload + upsert both, save cursor."""
    source = _fake_source()
    docs = [
        _make_source_doc(doc_id="a", title="A", size=2048),
        _make_source_doc(doc_id="b", title="B", size=4096),
    ]

    # Build a connector mock
    fake_connector = MagicMock()
    fake_connector.source_type = "google_drive"
    fake_connector.validate_credentials = AsyncMock()
    fake_connector.list_changes = AsyncMock(return_value=(docs, "next-cursor-1"))
    fake_connector.fetch_doc = AsyncMock(
        side_effect=[(b"bytes-a", docs[0]), (b"bytes-b", docs[1])]
    )
    fake_connector.aclose = AsyncMock()

    # Patch all the engine's external deps
    with patch("app.sources.sync.get_session_factory") as mock_factory, \
         patch("app.sources.sync.build_connector", return_value=fake_connector), \
         patch("app.sources.sync.upload_doc", new=AsyncMock()) as mock_upload, \
         patch("app.sources.sync.publish_event", new=AsyncMock()) as mock_pub, \
         patch("app.sources.sync._upsert_document", new=AsyncMock()) as mock_upsert, \
         patch("app.sources.sync._mark_source_last_sync", new=AsyncMock()), \
         patch("app.sources.sync._set_source_cursor", new=AsyncMock()) as mock_cursor, \
         patch("app.sources.sync._finalize_job", new=AsyncMock()) as mock_finalize, \
         patch("app.sources.sync._set_job_total", new=AsyncMock()):

        # The session factory returns a context manager; configure the session
        # returned by __aenter__ to return `source` from execute().
        session_mock = _make_session_with_source(source)
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(
            return_value=session_mock
        )
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_sync(source_id=str(source.id), job_id="job-1", triggered_by="manual")

    # Verify the happy-path side effects
    fake_connector.validate_credentials.assert_awaited_once()
    fake_connector.list_changes.assert_awaited_once()
    assert fake_connector.fetch_doc.await_count == 2
    assert mock_upload.await_count == 2
    assert mock_upsert.await_count == 2
    mock_cursor.assert_awaited_once_with(str(source.id), "next-cursor-1")
    mock_finalize.assert_awaited_once()
    # Status should be COMPLETED (no failures). final_status is the 2nd positional arg.
    assert mock_finalize.call_args.args[1] == "completed"
    assert mock_finalize.call_args.kwargs["failed"] == 0
    # Progress events: at least start + 2*fetch + complete
    assert mock_pub.await_count >= 4


@pytest.mark.asyncio
async def test_run_sync_skips_oversized_doc_as_skip_event() -> None:
    source = _fake_source()
    big = _make_source_doc(doc_id="big", title="Big", size=200 * 1024 * 1024)  # 200MB
    small = _make_source_doc(doc_id="small", title="Small", size=1024)
    docs = [big, small]

    fake_connector = MagicMock()
    fake_connector.validate_credentials = AsyncMock()
    fake_connector.list_changes = AsyncMock(return_value=(docs, "c"))
    fake_connector.fetch_doc = AsyncMock(return_value=(b"x", small))
    fake_connector.aclose = AsyncMock()

    with patch("app.sources.sync.get_session_factory") as mock_factory, \
         patch("app.sources.sync.build_connector", return_value=fake_connector), \
         patch("app.sources.sync.upload_doc", new=AsyncMock()) as mock_upload, \
         patch("app.sources.sync.publish_event", new=AsyncMock()), \
         patch("app.sources.sync._upsert_document", new=AsyncMock()) as mock_upsert, \
         patch("app.sources.sync._mark_source_last_sync", new=AsyncMock()), \
         patch("app.sources.sync._set_source_cursor", new=AsyncMock()), \
         patch("app.sources.sync._finalize_job", new=AsyncMock()) as mock_finalize, \
         patch("app.sources.sync._set_job_total", new=AsyncMock()):

        session_mock = _make_session_with_source(source)
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session_mock)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_sync(source_id=str(source.id), job_id="job-2", triggered_by="manual")

    # Big doc was skipped, small was fetched+uploaded
    assert fake_connector.fetch_doc.await_count == 1
    assert mock_upload.await_count == 1
    assert mock_upsert.await_count == 1
    # Finalize says PARTIAL (1 indexed, 1 failed). final_status is 2nd positional arg.
    assert mock_finalize.call_args.args[1] == "partial"
    assert mock_finalize.call_args.kwargs["indexed"] == 1
    assert mock_finalize.call_args.kwargs["failed"] == 1


@pytest.mark.asyncio
async def test_run_sync_marks_source_auth_failed_on_auth_error() -> None:
    """A 401 from the connector must set Source.status = 'auth_failed' and
    fail the job (not retry)."""
    from app.sources.base import ConnectorAuthError

    source = _fake_source()
    fake_connector = MagicMock()
    fake_connector.validate_credentials = AsyncMock(
        side_effect=ConnectorAuthError("token expired")
    )
    fake_connector.aclose = AsyncMock()

    with patch("app.sources.sync.get_session_factory") as mock_factory, \
         patch("app.sources.sync.build_connector", return_value=fake_connector), \
         patch("app.sources.sync._mark_source_status", new=AsyncMock()) as mock_status, \
         patch("app.sources.sync._finalize_job", new=AsyncMock()) as mock_finalize:

        session_mock = _make_session_with_source(source)
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session_mock)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_sync(source_id=str(source.id), job_id="job-3", triggered_by="manual")

    # Source marked auth_failed, job failed
    mock_status.assert_awaited_once()
    args = mock_status.await_args.args
    assert args[0] == str(source.id)
    assert args[1] == "auth_failed"
    mock_finalize.assert_awaited_once()
    assert mock_finalize.await_args.args[1] == "failed"
