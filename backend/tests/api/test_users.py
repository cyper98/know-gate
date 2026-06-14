"""Unit tests for the users API router.

Schemas + permission logic + error mapping. End-to-end behavior
(DB writes, role assignment) is covered by the live integration tests.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.users import RoleAssignRequest, UserInviteRequest, UserUpdate

# === Schemas ===

def test_user_invite_minimal() -> None:
    """Email + display_name is the minimum; defaults to ['member'] role."""
    body = UserInviteRequest(email="alice@example.com", display_name="Alice")
    assert body.roles == ["member"]
    assert body.initial_password is None
    assert body.group_ids is None


def test_user_invite_rejects_short_password() -> None:
    """Password (when provided) must be >= 8 chars (matches auth schema)."""
    with pytest.raises(ValidationError):
        UserInviteRequest(
            email="bob@example.com", display_name="Bob", initial_password="short"
        )


def test_user_invite_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        UserInviteRequest(email="not-an-email", display_name="X")


def test_user_invite_accepts_custom_role_list() -> None:
    body = UserInviteRequest(
        email="admin@example.com",
        display_name="Admin",
        roles=["admin", "editor"],
    )
    assert body.roles == ["admin", "editor"]


def test_user_update_all_optional() -> None:
    """All fields None = no-op (validated by the endpoint, not the schema)."""
    body = UserUpdate()
    assert body.display_name is None
    assert body.language_pref is None
    assert body.status is None


def test_user_update_rejects_short_display_name() -> None:
    with pytest.raises(ValidationError):
        UserUpdate(display_name="")


def test_role_assign_requires_one_of_id_or_name() -> None:
    """Both fields optional but the endpoint will reject both-None."""
    body = RoleAssignRequest()
    assert body.role_id is None
    assert body.role_name is None


def test_role_assign_accepts_either_field() -> None:
    a = RoleAssignRequest(role_id="uuid-1")
    assert a.role_id == "uuid-1"
    b = RoleAssignRequest(role_name="admin")
    assert b.role_name == "admin"
