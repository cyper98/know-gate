"""Tests for the user sub-commands."""

from __future__ import annotations

import httpx
import pytest

from knowgate_cli.output import Output
from knowgate_cli.user import (
    assign_role,
    delete_user,
    invite_user,
    list_users,
    revoke_role,
    show_user,
)


@pytest.fixture()
def users_list_response() -> dict:
    return {
        "data": [
            {
                "id": "u1234567890",
                "email": "alice@e.com",
                "display_name": "Alice",
                "language_pref": "en",
                "status": "active",
                "last_login_at": "2026-06-14T10:00:00Z",
                "roles": ["admin"],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-06-14T10:00:00Z",
            },
        ],
        "meta": {"limit": 50, "next_cursor": None},
    }


class TestListUsers:
    def test_returns_rows(self, client, mock_http, users_list_response) -> None:
        mock_http.get("/api/v1/users").mock(
            return_value=httpx.Response(200, json=users_list_response)
        )
        out = Output(json_mode=True)
        rows = list_users(client, out)
        assert rows[0]["email"] == "alice@e.com"

    def test_passes_filters(self, client, mock_http) -> None:
        route = mock_http.get("/api/v1/users").mock(
            return_value=httpx.Response(200, json={"data": [], "meta": {}})
        )
        out = Output()
        list_users(
            client,
            out,
            status="active",
            email_contains="alice",
            limit=10,
        )
        sent = route.calls.last.request
        assert sent.url.params.get("status") == "active"
        assert sent.url.params.get("email_contains") == "alice"
        assert sent.url.params.get("limit") == "10"


class TestShowUser:
    def test_returns_row(self, client, mock_http) -> None:
        mock_http.get("/api/v1/users/u1").mock(
            return_value=httpx.Response(
                200,
                json={"id": "u1", "email": "a@e.com", "display_name": "A"},
            )
        )
        out = Output(json_mode=True)
        row = show_user(client, out, "u1")
        assert row["email"] == "a@e.com"


class TestInviteUser:
    def test_post_payload(self, client, mock_http) -> None:
        route = mock_http.post("/api/v1/users").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "u1",
                    "email": "new@e.com",
                    "display_name": "New",
                    "status": "active",
                    "roles": ["member"],
                    "groups": [],
                    "initial_password": "RandomPwd123",
                },
            )
        )
        out = Output(json_mode=True)
        body = invite_user(
            client,
            out,
            email="new@e.com",
            display_name="New",
            roles=["member"],
        )
        assert body["initial_password"] == "RandomPwd123"
        import json as _json

        sent = _json.loads(route.calls.last.request.content)
        assert sent["email"] == "new@e.com"
        assert sent["roles"] == ["member"]


class TestDeleteUser:
    def test_with_yes_skips_confirm(self, client, mock_http) -> None:
        route = mock_http.delete("/api/v1/users/u1").mock(return_value=httpx.Response(204))
        out = Output()
        delete_user(client, out, "u1", yes=True)
        assert route.called


class TestRoleOps:
    def test_assign_role(self, client, mock_http) -> None:
        route = mock_http.post("/api/v1/users/u1/roles").mock(
            return_value=httpx.Response(
                201, json={"user_id": "u1", "role": "editor", "role_id": "r1"}
            )
        )
        out = Output(json_mode=True)
        body = assign_role(client, out, "u1", "editor")
        assert body["role"] == "editor"
        import json as _json

        sent = _json.loads(route.calls.last.request.content)
        assert sent == {"role_name": "editor"}

    def test_assign_role_noop(self, client, mock_http) -> None:
        """If the server says noop, the response carries that hint."""
        mock_http.post("/api/v1/users/u1/roles").mock(
            return_value=httpx.Response(201, json={"user_id": "u1", "role": "editor", "noop": True})
        )
        out = Output(json_mode=True)
        body = assign_role(client, out, "u1", "editor")
        assert body["noop"] is True

    def test_revoke_role(self, client, mock_http) -> None:
        route = mock_http.delete("/api/v1/users/u1/roles/r1").mock(return_value=httpx.Response(204))
        out = Output()
        revoke_role(client, out, "u1", "r1", yes=True)
        assert route.called
