"""Unit tests for the roles API router (schemas + validation helpers)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.roles import (
    STATIC_ROLE_NAMES,
    RoleCreate,
    RoleUpdate,
    _validate_permissions,
)

# === Schemas ===

def test_role_create_minimal() -> None:
    body = RoleCreate(name="reviewer")
    assert body.name == "reviewer"
    assert body.permissions == []  # default
    assert body.description is None


def test_role_create_rejects_uppercase_name() -> None:
    """Role names are kebab-case identifiers; no whitespace, no uppercase."""
    with pytest.raises(ValidationError):
        RoleCreate(name="Bad Name")


def test_role_create_rejects_spaces() -> None:
    with pytest.raises(ValidationError):
        RoleCreate(name="with spaces")


def test_role_create_accepts_kebab_case() -> None:
    body = RoleCreate(name="limited-reviewer")
    assert body.name == "limited-reviewer"


def test_role_create_accepts_underscores() -> None:
    """Pattern allows underscores too (some orgs use `read_only`)."""
    body = RoleCreate(name="read_only")
    assert body.name == "read_only"


def test_role_update_all_optional() -> None:
    body = RoleUpdate()
    assert body.name is None
    assert body.description is None
    assert body.permissions is None


def test_static_role_names_contains_seeded_set() -> None:
    """admin/editor/member are the 3 seeded roles (cannot be renamed)."""
    assert frozenset({"admin", "editor", "member"}) == STATIC_ROLE_NAMES


# === Permission validation ===

def test_validate_permissions_accepts_known() -> None:
    """All known Permission enum values pass."""
    _validate_permissions(["view_doc", "manage_users"])


def test_validate_permissions_rejects_unknown() -> None:
    """Unknown strings raise an api_error (mapped to 400 by the handler)."""

    with pytest.raises(Exception) as exc_info:
        _validate_permissions(["view_doc", "totally_fake_perm"])
    # The exception is an HTTPException with the standard envelope shape
    assert "totally_fake_perm" in str(exc_info.value)


def test_validate_permissions_empty_is_ok() -> None:
    """An empty list means 'no permissions' (custom role with no grants)."""
    _validate_permissions([])


def test_validate_permissions_all_known() -> None:
    """All known permissions at once should validate."""
    from app.auth.permissions import Permission

    _validate_permissions([p.value for p in Permission])
