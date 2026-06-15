"""Tests for the auth sub-commands + keyring sidecar."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import keyring
import pytest
import respx
from typer.testing import CliRunner

from knowgate_cli import auth as auth_mod
from knowgate_cli.client import KnowGateClient
from knowgate_cli.main import app
from knowgate_cli.output import Output


@pytest.fixture(autouse=True)
def isolated_keyring(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Use a tmp keyring dir for every test so the host keyring stays clean.

    We use a *file* keyring backend pointed at the tmp dir so the test
    doesn't depend on the host having macOS Keychain / GNOME Keyring
    available in the test sandbox.
    """
    ring_path = tmp_path / "keyring.json"
    monkeypatch.setenv("KNOWGATE_CONFIG_DIR", str(tmp_path / "config"))
    # Configure a file-backed keyring
    import keyring.backend
    import keyring.credentials
    import keyring.errors

    class _FileKeyring(keyring.backend.KeyringBackend):
        """Tiny file-backed keyring for tests."""

        def __init__(self, path: Path) -> None:
            self.path = path
            if not path.exists():
                path.write_text("{}")

        def _load(self) -> dict[str, str]:
            return json.loads(self.path.read_text())

        def _save(self, data: dict[str, str]) -> None:
            self.path.write_text(json.dumps(data, indent=2))

        def set_password(self, service: str, username: str, password: str) -> None:
            data = self._load()
            data[f"{service}::{username}"] = password
            self._save(data)

        def get_password(self, service: str, username: str) -> str | None:
            return self._load().get(f"{service}::{username}")

        def delete_password(self, service: str, username: str) -> None:
            data = self._load()
            data.pop(f"{service}::{username}", None)
            self._save(data)

    keyring.set_keyring(_FileKeyring(ring_path))


class TestStoredCredentials:
    """JSON round-trip for the keyring payload."""

    def test_to_from_json(self) -> None:
        creds = auth_mod.StoredCredentials(
            access_token="AT",
            refresh_token="RT",
            user={"id": "u1", "email": "a@e.com", "roles": ["admin"]},
        )
        raw = creds.to_json()
        round_tripped = auth_mod.StoredCredentials.from_json(raw)
        assert round_tripped.access_token == "AT"
        assert round_tripped.refresh_token == "RT"
        assert round_tripped.user["email"] == "a@e.com"

    def test_from_corrupt_json_returns_none(self, isolated_config_dir: Path) -> None:
        # Manually inject a corrupt entry into the test keyring
        api_url = "http://test"
        email = "a@e.com"
        keyring.set_password(
            auth_mod.SERVICE_NAME,
            auth_mod._account_for(api_url, email),
            "not json",
        )
        assert auth_mod._load(api_url, email) is None


class TestActiveCredentials:
    def test_call_returns_none_when_unbound(self) -> None:
        holder = auth_mod._ActiveCredentials("http://t", "", None)
        assert holder() is None

    def test_call_returns_pair_when_loaded(self) -> None:
        creds = auth_mod.StoredCredentials(access_token="AT", refresh_token="RT", user={})
        holder = auth_mod._ActiveCredentials("http://t", "a@e", creds)
        assert holder() == ("AT", "RT")

    def test_set_tokens_updates_in_memory(self) -> None:
        creds = auth_mod.StoredCredentials(
            access_token="OLD", refresh_token="OLD-R", user={"id": "u1"}
        )
        holder = auth_mod._ActiveCredentials("http://t", "a@e", creds)
        holder.set_tokens("NEW", "NEW-R")
        assert holder() == ("NEW", "NEW-R")
        # user metadata preserved
        assert holder.creds is not None
        assert holder.creds.user == {"id": "u1"}


class TestLogin:
    def test_login_stores_creds(self, monkeypatch, isolated_config_dir) -> None:
        runner = CliRunner()

        # Stub the prompts: email + password
        answers = iter(["alice@e.com", "secret123"])
        output = Output()
        monkeypatch.setattr(output, "prompt_email", lambda msg: next(answers))
        monkeypatch.setattr(output, "prompt_password", lambda msg="Password": next(answers))
        # Patch the global _make_output to return our stubbed one
        from knowgate_cli import main as main_mod

        monkeypatch.setattr(main_mod, "_make_output", lambda ctx: output)

        # Stub the HTTP client to return a valid login response
        def _fake_make_client(_ctx):
            return KnowGateClient(base_url="http://test", credential_getter=lambda: None)

        monkeypatch.setattr(main_mod, "_make_client", _fake_make_client)

        # Patch the client.post to return a fake login response
        with respx.mock(base_url="http://test") as router:
            route = router.post("/api/v1/auth/login").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": "AT",
                        "refresh_token": "RT",
                        "token_type": "bearer",
                        "expires_in": 900,
                        "user": {
                            "id": "u1",
                            "email": "alice@e.com",
                            "display_name": "Alice",
                            "roles": ["admin"],
                        },
                    },
                )
            )
            result = runner.invoke(
                app,
                ["--api-url", "http://test", "auth", "login"],
                input="alice@e.com\nsecret123\n",
            )
            assert result.exit_code == 0, result.output
            assert route.called
            # And the credentials landed in the keyring
            stored = keyring.get_password(
                auth_mod.SERVICE_NAME,
                auth_mod._account_for("http://test", "alice@e.com"),
            )
            assert stored is not None
            creds = auth_mod.StoredCredentials.from_json(stored)
            assert creds.access_token == "AT"


class TestLogout:
    def test_logout_specific_email(self, isolated_config_dir) -> None:
        # Pre-populate the keyring
        creds = auth_mod.StoredCredentials(access_token="AT", refresh_token="RT", user={})
        auth_mod._store("http://test", "a@e.com", creds)
        auth_mod._add_to_index("http://test", "a@e.com")

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["--api-url", "http://test", "auth", "logout", "--email", "a@e.com"],
        )
        assert result.exit_code == 0
        assert (
            keyring.get_password(
                auth_mod.SERVICE_NAME,
                auth_mod._account_for("http://test", "a@e.com"),
            )
            is None
        )

    def test_logout_all(self, isolated_config_dir) -> None:
        for email in ("a@e.com", "b@e.com"):
            auth_mod._store(
                "http://test",
                email,
                auth_mod.StoredCredentials(access_token="AT", refresh_token="RT", user={}),
            )
            auth_mod._add_to_index("http://test", email)

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["--api-url", "http://test", "auth", "logout", "--all"],
        )
        assert result.exit_code == 0
        for email in ("a@e.com", "b@e.com"):
            assert (
                keyring.get_password(
                    auth_mod.SERVICE_NAME,
                    auth_mod._account_for("http://test", email),
                )
                is None
            )


class TestStatus:
    def test_status_while_logged_in(self, isolated_config_dir) -> None:
        creds = auth_mod.StoredCredentials(
            access_token="AT",
            refresh_token="RT",
            user={
                "id": "u1",
                "email": "a@e.com",
                "display_name": "Alice",
                "roles": ["admin", "editor"],
            },
        )
        auth_mod._store("http://test", "a@e.com", creds)
        auth_mod._add_to_index("http://test", "a@e.com")

        runner = CliRunner()
        result = runner.invoke(app, ["--api-url", "http://test", "--json", "auth", "status"])
        assert result.exit_code == 0
        body = json.loads(result.output)
        # In --json mode the table row is a single dict
        assert body[0]["email"] == "a@e.com"
        assert "admin" in body[0]["roles"]

    def test_status_when_not_logged_in(self, isolated_config_dir) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["--api-url", "http://test", "auth", "status"])
        assert result.exit_code == 0
        assert "Not signed in" in result.output
