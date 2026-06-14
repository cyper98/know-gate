"""Unit tests for the groups API router."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.groups import GroupCreate, GroupDocumentRequest, GroupMemberRequest, GroupUpdate


def test_group_create_minimal() -> None:
    body = GroupCreate(name="engineering")
    assert body.name == "engineering"
    assert body.description is None


def test_group_create_rejects_invalid_name() -> None:
    """Names are kebab-case identifiers (matches roles pattern)."""
    with pytest.raises(ValidationError):
        GroupCreate(name="Eng Group")


def test_group_update_all_optional() -> None:
    body = GroupUpdate()
    assert body.name is None
    assert body.description is None


def test_member_request_requires_user_id() -> None:
    body = GroupMemberRequest(user_id="u1")
    assert body.user_id == "u1"


def test_document_request_requires_document_id() -> None:
    body = GroupDocumentRequest(document_id="d1")
    assert body.document_id == "d1"
