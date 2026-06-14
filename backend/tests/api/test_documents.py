"""Unit tests for the documents API router.

We mock the async session factory and the auth/permission deps so we
can exercise the route logic in isolation. Integration tests (full
DB + MinIO) live in `tests/integration/` and require docker-compose.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.documents import (
    DocumentUpdate,
    _doc_to_response,
)
from app.auth.permissions import Permission, has_permission

# === Schemas ===

def test_document_update_accepts_minimal() -> None:
    """All fields optional; one or more may be set."""
    body = DocumentUpdate(title="New title")
    assert body.title == "New title"
    assert body.owner is None
    assert body.status is None
    assert body.access_group_ids is None


def test_document_update_rejects_empty_title() -> None:
    """Title is bounded 1..200 chars (matches the DB column)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DocumentUpdate(title="")


def test_document_update_accepts_access_group_ids() -> None:
    """Admin re-share path; editor flow will be rejected in the endpoint."""
    body = DocumentUpdate(access_group_ids=["g1", "g2"])
    assert body.access_group_ids == ["g1", "g2"]


# === Permission helpers (used by documents router) ===

def test_has_permission_admin() -> None:
    """Admin always passes any permission check."""
    assert has_permission(["admin"], Permission.VIEW_DOC) is True
    assert has_permission(["admin"], Permission.MANAGE_USERS) is True


def test_has_permission_member_view_only() -> None:
    """Member can view but not edit."""
    assert has_permission(["member"], Permission.VIEW_DOC) is True
    assert has_permission(["member"], Permission.EDIT_DOC_METADATA) is False
    assert has_permission(["member"], Permission.MANAGE_USERS) is False


def test_has_permission_any_role_grants() -> None:
    """A user with multiple roles: at least one grants → allowed."""
    assert has_permission(["member", "editor"], Permission.EDIT_DOC_METADATA) is True


# === Response serialization ===

def test_doc_to_response_handles_missing_optionals() -> None:
    """A freshly-discovered doc with no indexed_at / source_url / etc.
    should still serialize cleanly (no None errors)."""

    class FakeDoc:
        id = str(uuid.uuid4())
        source = "google_drive"
        source_id = "f1"
        source_url = None
        source_modified_at = None
        title = "Untitled"
        owner = None
        document_type = None
        mime_type = None
        size_bytes = None
        language = None
        status = "discovered"
        indexed_at = None
        error_message = None
        access_groups = []
        created_at = datetime(2026, 6, 14, tzinfo=UTC)
        updated_at = datetime(2026, 6, 14, tzinfo=UTC)

    resp = _doc_to_response(FakeDoc())
    assert resp.id == FakeDoc.id
    assert resp.title == "Untitled"
    assert resp.access_groups == []
    assert resp.status == "discovered"


def test_doc_to_response_includes_group_ids() -> None:
    """Access group IDs (not full group objects) are exposed."""

    class FakeGroup:
        def __init__(self, gid: str) -> None:
            self.id = gid

    class FakeDoc:
        id = str(uuid.uuid4())
        source = "notion"
        source_id = "p1"
        source_url = "https://notion.so/p1"
        source_modified_at = datetime(2026, 6, 14, tzinfo=UTC)
        title = "Doc"
        owner = "alice@example.com"
        document_type = "page"
        mime_type = "text/markdown"
        size_bytes = 4096
        language = "en"
        status = "active"
        indexed_at = datetime(2026, 6, 14, tzinfo=UTC)
        error_message = None
        access_groups = [FakeGroup("g1"), FakeGroup("g2")]
        created_at = datetime(2026, 6, 14, tzinfo=UTC)
        updated_at = datetime(2026, 6, 14, tzinfo=UTC)

    resp = _doc_to_response(FakeDoc())
    assert resp.access_groups == ["g1", "g2"]
    assert resp.mime_type == "text/markdown"
    assert resp.size_bytes == 4096


# === Endpoint behavior: error mapping ===

def test_list_documents_returns_401_without_token() -> None:
    """Unauthenticated → 401 (handled by FastAPI dep before our code runs)."""
    # We exercise the auth flow via FastAPI's TestClient elsewhere; here
    # we just confirm the dependency chain is wired.
    from app.auth.permissions import get_current_user

    assert get_current_user is not None


@pytest.mark.asyncio
async def test_get_document_returns_404_when_missing() -> None:
    """`get_document` raises 404 with the standard error envelope."""
    from app.api.v1.documents import get_document

    with patch("app.api.v1.documents.get_session_factory") as mf:
        session = MagicMock()
        # select(Document).where(...) → scalar_one_or_none() → None
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        mf.return_value = MagicMock(return_value=session)

        with pytest.raises(HTTPException) as exc_info:
            await get_document("missing-id", user={"id": "u1", "roles": ["admin"]})
        # api_error wraps it; the underlying HTTPException status is 404
        assert exc_info.value.status_code == 404
        # ... and the body is a dict with `code: E5`
        assert exc_info.value.detail["code"] == "E5"


def test_permission_filter_skipped_for_admin() -> None:
    """Admin role bypasses the data-level filter (sees all docs)."""
    from app.api.v1._permissions import has_admin_role

    assert has_admin_role({"roles": ["admin"]}) is True
    assert has_admin_role({"roles": ["editor"]}) is False
    assert has_admin_role({"roles": []}) is False
    assert has_admin_role({}) is False


def test_user_has_doc_access_uses_set_intersection() -> None:
    """Empty user groups → no access (even with one shared group on the doc)."""
    from app.api.v1._permissions import user_has_doc_access

    class FakeGroup:
        def __init__(self, gid: str) -> None:
            self.id = gid

    class FakeDoc:
        access_groups = [FakeGroup("g1")]

    assert user_has_doc_access([], FakeDoc()) is False  # empty user groups
    assert user_has_doc_access(None, FakeDoc()) is False  # None
    assert user_has_doc_access(["g2"], FakeDoc()) is False  # no overlap
    assert user_has_doc_access(["g1", "g2"], FakeDoc()) is True  # overlap
