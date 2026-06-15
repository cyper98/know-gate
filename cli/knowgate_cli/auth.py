"""Auth sub-commands (``kg auth login`` / ``logout`` / ``status``).

Credentials are stored in the **system keyring** via :mod:`keyring`. The
keyring "service" is ``knowgate-cli`` and the username is the lowercase
email — this lets a user have multiple KnowGate accounts on the same
machine (work + personal) without overwriting each other.

The stored value is a JSON blob ``{"access": "...", "refresh": "...", "user": {...}}``
so :func:`make_getter` can hand both tokens to the HTTP client in one
call. Refresh is initiated by the client on a 401 response, not here.

If the system keyring is unavailable (headless server, locked
secret-service), :class:`keyring.errors.KeyringError` is caught and
re-raised as :class:`AuthError` with a clear hint to set
``KNOWGATE_CREDENTIALS_FILE`` (future) or run on a desktop session.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
import keyring.errors

from .client import KnowGateClient
from .output import Output

SERVICE_NAME = "knowgate-cli"
_KEYRING_NAMESPACE = "knowgate-cli"


class AuthError(RuntimeError):
    """Raised on credential store failures (keyring missing, etc.)."""


@dataclass(frozen=True)
class StoredCredentials:
    """What we keep in keyring for one (api_url, email) pair."""

    access_token: str
    refresh_token: str
    user: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {
                "access": self.access_token,
                "refresh": self.refresh_token,
                "user": self.user,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str) -> StoredCredentials:
        data = json.loads(raw)
        return cls(
            access_token=data["access"],
            refresh_token=data["refresh"],
            user=data.get("user", {}),
        )


# === Keyring key derivation ===
# We namespace by API URL + email so multiple accounts coexist and
# changing the API URL doesn't accidentally reuse the wrong creds.


def _account_for(api_url: str, email: str) -> str:
    """Derive a stable keyring account name from ``api_url + email``.

    The API URL is hashed (8 hex chars) to keep the keyring account name
    short — macOS keychain and Windows credential store both have a
    practical account-name length cap. Email is lowercased.
    """
    url_hash = hashlib.sha256(api_url.encode("utf-8")).hexdigest()[:8]
    return f"{url_hash}:{email.lower()}"


def _store(api_url: str, email: str, creds: StoredCredentials) -> None:
    """Persist creds to keyring under the derived account name."""
    try:
        keyring.set_password(SERVICE_NAME, _account_for(api_url, email), creds.to_json())
    except keyring.errors.KeyringError as exc:
        raise AuthError(
            f"Could not store credentials in system keyring: {exc}. "
            f"Make sure a keyring backend is available "
            f"(e.g. GNOME Keyring, KWallet, macOS Keychain, Windows Credential Manager)."
        ) from exc


def _load(api_url: str, email: str) -> StoredCredentials | None:
    """Load creds from keyring, returning ``None`` if absent."""
    try:
        raw = keyring.get_password(SERVICE_NAME, _account_for(api_url, email))
    except keyring.errors.KeyringError:
        return None
    if not raw:
        return None
    try:
        return StoredCredentials.from_json(raw)
    except (ValueError, KeyError):
        # Corrupt entry — clear it so the next call starts clean.
        _clear(api_url, email)
        return None


def _clear(api_url: str, email: str) -> None:
    """Remove the keyring entry for ``api_url + email`` (no-op if absent)."""
    try:
        keyring.delete_password(SERVICE_NAME, _account_for(api_url, email))
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError:
        # No-op: best-effort cleanup
        pass


def _all_accounts() -> list[tuple[str, str]]:
    """Return all (api_url, email) pairs we have creds for.

    Keyring has no portable "list all" API, so we maintain a sidecar
    index file in the same config dir. Cheap to write, lets ``logout``
    without an email arg iterate everything.
    """
    index_path = _index_path()
    if not index_path.exists():
        return []
    try:
        with index_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            return []
        return [(d["api_url"], d["email"]) for d in data if "api_url" in d and "email" in d]
    except (ValueError, OSError):
        return []


def _index_path() -> Path:
    """Location of the sidecar index file listing known (api_url, email) pairs."""
    override = os.environ.get("KNOWGATE_CONFIG_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".config" / "knowgate"
    base.mkdir(parents=True, exist_ok=True)
    return base / "credential_index.json"


def _add_to_index(api_url: str, email: str) -> None:
    """Add a (api_url, email) pair to the sidecar index (idempotent)."""
    path = _index_path()
    current = _all_accounts()
    pair = (api_url, email)
    if pair in current:
        return
    current.append(pair)
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(
                [{"api_url": u, "email": e} for u, e in current],
                fh,
                indent=2,
            )
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    except OSError as exc:
        raise AuthError(f"Could not write credential index: {exc}") from exc


def _remove_from_index(api_url: str, email: str) -> None:
    path = _index_path()
    if not path.exists():
        return
    remaining = [(u, e) for u, e in _all_accounts() if not (u == api_url and e == email)]
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(
                [{"api_url": u, "email": e} for u, e in remaining],
                fh,
                indent=2,
            )
    except OSError:
        pass


# === Credential getter for the HTTP client ===
# Returns a Callable that knows how to read AND update the in-memory
# credential cache. The client calls it on every request; we also need
# a way to swap the active email when the user runs `kg auth login`
# as a different account.


class _ActiveCredentials:
    """Mutable holder for the current (email, creds) pair.

    The HTTP client reads via ``()`` and writes via ``set_tokens``.
    """

    def __init__(self, api_url: str, email: str, creds: StoredCredentials | None) -> None:
        self.api_url = api_url
        self.email = email
        self.creds = creds

    def __call__(self) -> tuple[str, str] | None:
        if self.creds is None:
            return None
        return (self.creds.access_token, self.creds.refresh_token)

    def set_tokens(self, access: str, refresh: str) -> None:
        """Update tokens in memory and persist to keyring."""
        if self.creds is None:
            self.creds = StoredCredentials(access_token=access, refresh_token=refresh, user={})
        else:
            self.creds = StoredCredentials(
                access_token=access,
                refresh_token=refresh,
                user=self.creds.user,
            )
        # Best-effort persist; if the keyring fails here, we still
        # keep the in-memory copy for this session.
        with contextlib.suppress(AuthError):
            _store(self.api_url, self.email, self.creds)


def make_getter(api_url: str, email: str | None = None) -> _ActiveCredentials:
    """Return a credential getter bound to ``api_url`` + ``email``.

    If ``email`` is ``None``, picks the first indexed account whose URL
    matches. Returns a holder whose ``creds`` attribute is ``None`` if
    no keyring entry is found — the client surfaces the right error
    ("not logged in") on the first request.
    """
    if email is None:
        for u, e in _all_accounts():
            if u == api_url:
                email = e
                break
    if email is None:
        return _ActiveCredentials(api_url, "", None)
    creds = _load(api_url, email)
    return _ActiveCredentials(api_url, email, creds)


# === Sub-commands ===


def login(client: KnowGateClient, out: Output) -> None:
    """``kg auth login`` — prompt email + password, call /auth/login, store in keyring."""
    email = out.prompt_email("Email")
    password = out.prompt_password("Password")
    with out.spinner("Signing in…"):
        try:
            body = client.post("/auth/login", json={"email": email, "password": password})
        except Exception as exc:
            out.error(str(exc), code=getattr(exc, "code", None))
            raise
    user = body.get("user", {})
    creds = StoredCredentials(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        user=user,
    )
    try:
        _store(client.base_url, email, creds)
        _add_to_index(client.base_url, email)
    except AuthError as exc:
        out.error(str(exc))
        raise
    out.success(f"Signed in as {user.get('email', email)} ({user.get('display_name', '')})")


def logout(api_url: str, email: str | None, all_accounts: bool, out: Output) -> None:
    """``kg auth logout`` — clear keyring entry (single account or all).

    We don't call ``/api/v1/auth/logout`` here because that's a server-side
    revocation that needs a live access token; the CLI's value is local
    cleanup. A user wanting to revoke a token server-side can use the
    web UI's "sign out" button or call the API directly.
    """
    if all_accounts:
        for u, e in _all_accounts():
            if u == api_url or all_accounts:
                _clear(u, e)
                _remove_from_index(u, e)
        out.success("Cleared all stored credentials.")
        return
    if email is None:
        # Try the currently active account
        for u, e in _all_accounts():
            if u == api_url:
                email = e
                break
    if not email:
        out.warning("No active session. Nothing to clear.")
        return
    _clear(api_url, email)
    _remove_from_index(api_url, email)
    out.success(f"Cleared credentials for {email}.")


def status(api_url: str, out: Output) -> None:
    """``kg auth status`` — show the currently active account (if any)."""
    accounts = [(u, e) for u, e in _all_accounts() if u == api_url]
    if not accounts:
        out.warning("Not signed in. Run `kg auth login` to authenticate.")
        return
    rows: list[dict[str, Any]] = []
    for _u, email in accounts:
        creds = _load(api_url, email)
        if creds is None:
            rows.append({"email": email, "status": "expired"})
            continue
        user = creds.user or {}
        rows.append(
            {
                "email": email,
                "display_name": user.get("display_name", ""),
                "roles": ",".join(user.get("roles", [])),
                "status": "active",
            }
        )
    out.table(
        rows,
        columns=[
            ("email", "Email"),
            ("display_name", "Name"),
            ("roles", "Roles"),
            ("status", "Status"),
        ],
    )
    out.info(f"API: {api_url}")


__all__ = [
    "SERVICE_NAME",
    "AuthError",
    "StoredCredentials",
    "login",
    "logout",
    "make_getter",
    "status",
]
