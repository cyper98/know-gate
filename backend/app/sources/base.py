"""Abstract base + shared types for all source connectors.

A connector is the adapter between a SaaS provider (Drive, Notion, ...) and
the sync engine. The engine knows about Documents, MinIO, Qdrant, Celery;
the connector knows about OAuth, the provider's API, pagination, and rate
limits. They meet at the `SourceDoc` dataclass + the 4 abstract methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# === Errors ===

class ConnectorError(Exception):
    """Base for all connector failures (re-raised by the sync engine)."""


class ConnectorAuthError(ConnectorError):
    """OAuth token expired / revoked / insufficient scope.

    The sync engine should mark the source as `AUTH_FAILED` and stop scheduling
    syncs for it until an admin reconnects.
    """


class ConnectorRateLimitError(ConnectorError):
    """Provider returned 429 / quota exceeded. Includes `retry_after` (seconds)."""

    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# === Shared types ===

@dataclass(frozen=True)
class SourceDoc:
    """One document or page as the connector sees it.

    The `id` is the provider's stable ID (e.g. Drive file ID, Notion page UUID)
    and is the natural key for upsert. `extra` carries provider-specific
    metadata (folder path, webViewLink, mime version, etc.) and is persisted
    on the `Document` row.
    """

    id: str
    title: str
    mime_type: str | None
    modified_at: datetime | None
    url: str | None
    size_bytes: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    is_deleted: bool = False  # set by `list_changes` for tombstones


# === Abstract base ===

class BaseSourceConnector(ABC):
    """Adapter contract for source connectors.

    Lifecycle:
        1. Caller (sync engine) loads a `Source` row from DB
        2. Caller decrypts `config_encrypted` into a dict
        3. Caller instantiates the concrete connector with that config
        4. Caller calls `list_changes(cursor)` to discover new/updated/deleted docs
        5. For each doc, caller calls `fetch_doc(id)` to download raw bytes
        6. Caller pipes bytes to the ingestion pipeline
    """

    source_type: str  # subclass sets this (e.g. "google_drive")

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        self.source_id = source_id
        self.config = config

    @abstractmethod
    async def validate_credentials(self) -> None:
        """Verify the OAuth token / integration token is still good.

        Raises:
            ConnectorAuthError: if the token is invalid or scopes are missing.
        """

    @abstractmethod
    async def list_changes(self, cursor: str | None) -> tuple[list[SourceDoc], str | None]:
        """List docs new or changed since `cursor`.

        Args:
            cursor: opaque cursor from the previous run (None = full first sync)

        Returns:
            (docs, next_cursor) — `docs` may be empty. `next_cursor` is passed
            back on the next call. Caller persists it on the `Source` row.

        The returned list MAY include `is_deleted=True` tombstones; the caller
        is responsible for marking the corresponding Document row as DELETED.
        """

    @abstractmethod
    async def fetch_doc(self, doc_id: str) -> tuple[bytes, SourceDoc]:
        """Download the raw bytes for one document + its current metadata.

        Returns:
            (raw_bytes, current_metadata) — metadata is fetched in the same
            call so the caller can persist the latest `modified_at` + `url`
            even if the download is partial.

        Raises:
            ConnectorAuthError: token expired mid-fetch
            ConnectorRateLimitError: 429 (caller should back off + retry)
        """
