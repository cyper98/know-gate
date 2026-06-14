"""Unit tests for the permission catalog and role-permission mapping."""

from __future__ import annotations

from app.auth.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    get_role_permissions,
    has_permission,
)


def test_admin_role_has_all_permissions() -> None:
    admin_perms = get_role_permissions("admin")
    assert admin_perms == frozenset(Permission)


def test_editor_role_has_view_and_edit_only() -> None:
    editor_perms = get_role_permissions("editor")
    assert Permission.VIEW_DOC in editor_perms
    assert Permission.EDIT_DOC_METADATA in editor_perms
    # editors must NOT manage users / roles / groups / sources / settings
    assert Permission.MANAGE_USERS not in editor_perms
    assert Permission.MANAGE_ROLES not in editor_perms
    assert Permission.MANAGE_GROUPS not in editor_perms
    assert Permission.MANAGE_SOURCES not in editor_perms
    assert Permission.MANAGE_SETTINGS not in editor_perms


def test_member_role_is_read_only() -> None:
    member_perms = get_role_permissions("member")
    assert Permission.VIEW_DOC in member_perms
    # everything else is forbidden
    assert Permission.EDIT_DOC_METADATA not in member_perms
    assert Permission.DELETE_DOC not in member_perms
    assert Permission.MANAGE_USERS not in member_perms


def test_unknown_role_returns_empty_permission_set() -> None:
    assert get_role_permissions("nonexistent") == frozenset()


def test_has_permission_returns_true_for_admin_any_action() -> None:
    for perm in Permission:
        assert has_permission(["admin"], perm) is True, f"admin should have {perm}"


def test_has_permission_returns_false_for_member_on_write_actions() -> None:
    assert has_permission(["member"], Permission.VIEW_DOC) is True
    assert has_permission(["member"], Permission.EDIT_DOC_METADATA) is False
    assert has_permission(["member"], Permission.MANAGE_USERS) is False


def test_has_permission_grants_if_any_role_grants() -> None:
    """A user with multiple roles: permission granted if ANY role has it."""
    # user has both member + admin: write actions should be allowed via admin
    assert has_permission(["member", "admin"], Permission.MANAGE_USERS) is True
    # user has both member + editor: edit allowed via editor
    assert has_permission(["member", "editor"], Permission.EDIT_DOC_METADATA) is True


def test_has_permission_returns_false_for_empty_role_list() -> None:
    assert has_permission([], Permission.VIEW_DOC) is False


def test_role_permissions_dict_covers_three_default_roles() -> None:
    """Frozen contract: admin/editor/member are the only built-in roles."""
    assert set(ROLE_PERMISSIONS.keys()) == {"admin", "editor", "member"}
