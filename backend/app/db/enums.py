"""Enum definitions for KnowGate domain (used as column values + API serialization)."""

from __future__ import annotations

from enum import Enum


class UserStatus(str, Enum):
    """User account status."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"  # Soft-deleted (GDPR)


class DocumentStatus(str, Enum):
    """Document lifecycle status (per brainstorm §6.3)."""

    DISCOVERED = "discovered"  # Sync found it, not yet processed
    INDEXING = "indexing"  # Parse + chunk + embed in progress
    ACTIVE = "active"  # Indexed + queryable
    OUTDATED = "outdated"  # last_updated > X months (cron marks)
    DEPRECATED = "deprecated"  # Admin marked
    ARCHIVED = "archived"  # Hidden from default search
    DELETED = "deleted"  # Hard-deleted after retention period


class SyncJobStatus(str, Enum):
    """Sync job lifecycle."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"  # Critical error (auth, quota)
    PARTIAL = "partial"  # Some docs OK, some failed


class SourceType(str, Enum):
    """Data source types."""

    GOOGLE_DRIVE = "google_drive"
    NOTION = "notion"


class SourceStatus(str, Enum):
    """Data source connection status."""

    ACTIVE = "active"
    AUTH_FAILED = "auth_failed"  # OAuth token expired
    PAUSED = "paused"  # Admin paused
    ARCHIVED = "archived"  # Removed from active list (cascade archive)


class UserQueryStatus(str, Enum):
    """User query lifecycle (per brainstorm §6.3)."""

    IN_PROGRESS = "in_progress"
    ANSWERED = "answered"
    NO_RESULT = "no_result"
    FAILED = "failed"  # LLM error after retries
    PERMISSION_DENIED = "permission_denied"  # All chunks filtered


class FeedbackRating(str, Enum):
    """User feedback on query answer."""

    GOOD = "good"
    BAD = "bad"
    SOURCE_MISSING = "source_missing"


class PermissionGrantStatus(str, Enum):
    """Permission grant lifecycle (e.g., invite acceptance)."""

    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
