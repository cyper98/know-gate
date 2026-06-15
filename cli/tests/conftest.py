"""Shared pytest fixtures for the KnowGate CLI test suite.

Centralises:
- A unique per-test ``KNOWGATE_CONFIG_DIR`` (so config writes don't
  touch the host's real ``~/.config/knowgate``).
- A no-credential credential getter (so sub-commands run as
  "not logged in" by default; individual tests can swap one in).
- A respx-mocked HTTP transport (no real network calls).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import respx

from knowgate_cli import auth as auth_mod
from knowgate_cli.client import KnowGateClient


@pytest.fixture()
def isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point ``KNOWGATE_CONFIG_DIR`` at a tmp dir for the test's lifetime.

    Both :mod:`knowgate_cli.config` and :mod:`knowgate_cli.auth` honour
    this env var, so all keyring-sidecar + config.toml writes stay in
    the temp dir and don't pollute the host filesystem.
    """
    d = tmp_path / "knowgate-cli-test"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KNOWGATE_CONFIG_DIR", str(d))
    # Reload the keyring index path to honour the override
    auth_mod._index_path.cache_clear() if hasattr(auth_mod._index_path, "cache_clear") else None
    yield d


@pytest.fixture()
def no_creds() -> auth_mod._ActiveCredentials:
    """A credential getter that returns ``None`` (anonymous)."""
    return auth_mod._ActiveCredentials(api_url="http://test", email="", creds=None)


@pytest.fixture()
def client(no_creds: auth_mod._ActiveCredentials) -> KnowGateClient:
    """A :class:`KnowGateClient` bound to the test API URL + no creds."""
    return KnowGateClient(
        base_url="http://test",
        credential_getter=no_creds,
    )


@pytest.fixture()
def mock_http() -> Iterator[respx.MockRouter]:
    """Respx mock router active for the test; transport is local-only."""
    with respx.mock(base_url="http://test") as router:
        yield router
