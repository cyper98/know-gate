"""Pydantic schemas for Qdrant chunk payload (validation at API + indexer)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# Qdrant payload field names (must match indexer)
class ChunkPayloadFields:
    """Field names used in Qdrant payload (single source of truth)."""

    DOC_ID = "doc_id"
    CHUNK_ID = "chunk_id"
    GROUP_IDS = "group_ids"
    LANGUAGE = "language"
    STATUS = "status"
    CHUNK_INDEX = "chunk_index"
    SECTION_TITLE = "section_title"
    INDEXED_AT = "indexed_at"
    SOURCE = "source"
    SOURCE_ID = "source_id"


# Status values stored in payload (mirror of app.db.enums.DocumentStatus)
class PayloadStatus:
    ACTIVE = "active"
    OUTDATED = "outdated"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ChunkPayload(BaseModel):
    """Payload for one Qdrant point (one chunk)."""

    doc_id: str = Field(..., description="Document UUID (FK to documents.id)")
    chunk_id: str = Field(..., description="Chunk UUID (FK to chunks.id)")
    group_ids: list[str] = Field(
        default_factory=list,
        description="Access group UUIDs this doc belongs to (for permission filter)",
    )
    language: str | None = Field(None, description="ISO 639-1 code (vi, en, zh, ...)")
    status: Literal["active", "outdated", "deprecated", "archived", "deleted"] = "active"
    chunk_index: int = Field(..., ge=0)
    section_title: str | None = None
    indexed_at: str | None = Field(None, description="ISO 8601 timestamp")
    source: str | None = Field(None, description="google_drive | notion | ...")
    source_id: str | None = None
