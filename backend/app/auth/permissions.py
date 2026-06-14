"""Permission enum + RBAC role-permission mapping + FastAPI dependencies.

Permission model (per brainstorm §6.2):
- 3 flat roles: admin, editor, member (no nested hierarchy)
- Each role has a static set of permissions
- Permission filter applied at API layer; defense in depth at Qdrant + response layer
- Access group model (user.groups ∩ doc.access_groups) is enforced separately
  at retrieval; this module only handles role-based action perms
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import TokenError, verify_token
from app.cache.helpers import is_jti_revoked


# === Permission catalog ===
class Permission(StrEnum):
    """All actions that can be permission-gated in the API."""

    # Documents
    VIEW_DOC = "view_doc"
    EDIT_DOC_METADATA = "edit_doc_metadata"
    DELETE_DOC = "delete_doc"

    # RBAC management
    MANAGE_USERS = "manage_users"
    MANAGE_ROLES = "manage_roles"
    MANAGE_GROUPS = "manage_groups"

    # Sources
    MANAGE_SOURCES = "manage_sources"

    # Settings
    MANAGE_SETTINGS = "manage_settings"

    # Invitation
    INVITE_USER = "invite_user"

    # Audit
    VIEW_AUDIT_LOG = "view_audit_log"


# === Role → permission mapping (static, per brainstorm OQ-7 resolved: flat 3 roles) ===
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": frozenset(Permission),  # admin = all permissions
    "editor": frozenset(
        {
            Permission.VIEW_DOC,
            Permission.EDIT_DOC_METADATA,
            # editors CANNOT manage users/roles/groups/sources/settings
        }
    ),
    "member": frozenset(
        {
            Permission.VIEW_DOC,
            # read-only
        }
    ),
}


def get_role_permissions(role_name: str) -> frozenset[Permission]:
    """Get the set of permissions granted to a role (empty for unknown roles)."""
    return ROLE_PERMISSIONS.get(role_name, frozenset())


def has_permission(role_names: list[str], required: Permission) -> bool:
    """Check if ANY of the user's roles grants the required permission."""
    return any(required in get_role_permissions(role_name) for role_name in role_names)


# === FastAPI security: Bearer token ===
_bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token (RS256)")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> dict:
    """FastAPI dependency: extract user from JWT bearer token.

    Returns:
        Dict with keys: `id`, `roles`, `jti`, `exp`

    Raises:
        HTTPException 401 if token missing, invalid, expired, or revoked
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        claims = verify_token(token, expected_type="access")
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    jti = claims.get("jti")
    if jti and await is_jti_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "id": claims["sub"],
        "roles": claims.get("roles", []),
        "jti": jti,
        "exp": claims.get("exp"),
    }


CurrentUser = Annotated[dict, Depends(get_current_user)]


def require_permission(required: Permission):
    """FastAPI dependency factory: check user has required permission.

    Usage:
        @router.delete("/docs/{id}", dependencies=[Depends(require_permission(Permission.DELETE_DOC))])
    """

    async def _checker(user: CurrentUser) -> dict:
        if not has_permission(user["roles"], required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {required.value}",
            )
        return user

    return _checker
