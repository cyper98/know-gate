"""User sub-commands (``kg user list`` / ``invite`` / ``show`` / ``delete`` / ``role``).

All operations require ``manage_users`` permission (admin role). The
``invite`` command returns the one-time plaintext password in JSON mode
so admins can script the share via a secret manager; in human mode the
password is printed once and the user is reminded to share it via a
secure channel.
"""

from __future__ import annotations

from typing import Any

from .client import KnowGateClient
from .output import Output


def list_users(
    client: KnowGateClient,
    out: Output,
    *,
    status: str | None = None,
    email_contains: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """``kg user list`` — paginated user list with optional filters."""
    params: dict[str, Any] = {"limit": min(max(limit, 1), 100)}
    if status:
        params["status"] = status
    if email_contains:
        params["email_contains"] = email_contains
    with out.spinner("Loading users…"):
        body = client.get("/users", params=params)
    rows = body.get("data", []) if isinstance(body, dict) else body
    if out.json_mode:
        out.json(body)
        return rows
    if not rows:
        out.info("No users found.")
        return []
    display = [
        {
            "id": r.get("id", "")[:8],
            "email": r.get("email", ""),
            "name": r.get("display_name", ""),
            "roles": ",".join(r.get("roles", [])),
            "status": r.get("status", ""),
            "last_login": r.get("last_login_at") or "—",
        }
        for r in rows
    ]
    out.table(
        display,
        columns=[
            ("id", "ID"),
            ("email", "Email"),
            ("name", "Name"),
            ("roles", "Roles"),
            ("status", "Status"),
            ("last_login", "Last Login"),
        ],
    )
    return rows


def show_user(client: KnowGateClient, out: Output, user_id: str) -> dict[str, Any]:
    """``kg user show <id>`` — single user detail (admin only)."""
    with out.spinner(f"Loading user {user_id}…"):
        row = client.get(f"/users/{user_id}")
    if out.json_mode:
        out.json(row)
        return row
    out.panel(
        "\n".join(
            f"[bold]{k.replace('_', ' ').title()}[/bold]: "
            f"{','.join(v) if isinstance(v, list) else v}"
            for k, v in row.items()
            if v is not None
        ),
        title=f"User {row.get('email', user_id)}",
    )
    return row


def invite_user(
    client: KnowGateClient,
    out: Output,
    *,
    email: str | None = None,
    display_name: str | None = None,
    roles: list[str] | None = None,
    initial_password: str | None = None,
) -> dict[str, Any]:
    """``kg user invite <email>`` — create a user, assign roles, return one-time password.

    In interactive mode (no flags) prompts for email + name. Roles default
    to ``["member"]``. The response includes ``initial_password`` which
    is the only time the plaintext is available — share it with the user
    out-of-band.
    """
    if email is None:
        email = out.prompt_email("Email")
    if display_name is None:
        display_name = out.prompt_text("Display name")
    if roles is None:
        roles_raw = out.prompt_text("Roles (comma-separated, default 'member')", default="member")
        roles = [r.strip() for r in roles_raw.split(",") if r.strip()]

    payload: dict[str, Any] = {
        "email": email,
        "display_name": display_name,
        "roles": roles,
    }
    if initial_password:
        payload["initial_password"] = initial_password

    with out.spinner(f"Inviting {email}…"):
        body = client.post("/users", json=payload)
    if out.json_mode:
        out.json(body)
        return body
    out.success(f"Invited {email}.")
    initial = body.get("initial_password", "")
    if initial:
        out.warning(
            f"One-time initial password: [bold]{initial}[/bold]\n"
            f"  Share this through a secure out-of-band channel. "
            f"It will NOT be shown again."
        )
    return body


def delete_user(
    client: KnowGateClient,
    out: Output,
    user_id: str,
    *,
    yes: bool = False,
) -> None:
    """``kg user delete <id>`` — soft-delete (GDPR) with confirmation."""
    if not yes and not out.confirm(
        f"Soft-delete user {user_id}? They lose access immediately.",
        default=False,
    ):
        out.info("Cancelled.")
        return
    with out.spinner(f"Deleting user {user_id}…"):
        client.delete(f"/users/{user_id}")
    out.success(f"User {user_id} deleted (soft).")


def assign_role(
    client: KnowGateClient,
    out: Output,
    user_id: str,
    role: str,
) -> dict[str, Any]:
    """``kg user role add <user_id> <role>`` — assign a role (by name)."""
    with out.spinner(f"Assigning role '{role}' to {user_id}…"):
        body = client.post(
            f"/users/{user_id}/roles",
            json={"role_name": role},
        )
    if out.json_mode:
        out.json(body)
    else:
        if body.get("noop"):
            out.info(f"User already has role '{role}'.")
        else:
            out.success(f"Assigned role '{role}'.")
    return body


def revoke_role(
    client: KnowGateClient,
    out: Output,
    user_id: str,
    role_id: str,
    *,
    yes: bool = False,
) -> None:
    """``kg user role remove <user_id> <role_id>`` — revoke a role (by ID)."""
    if not yes and not out.confirm(f"Revoke role {role_id} from user {user_id}?", default=False):
        out.info("Cancelled.")
        return
    with out.spinner(f"Revoking role {role_id}…"):
        client.delete(f"/users/{user_id}/roles/{role_id}")
    out.success("Role revoked.")


__all__ = [
    "assign_role",
    "delete_user",
    "invite_user",
    "list_users",
    "revoke_role",
    "show_user",
]
