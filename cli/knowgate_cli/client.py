"""HTTP client + error envelope mapping for the KnowGate CLI.

Single sync :class:`httpx.Client` reused across sub-commands. The client:

- Attaches ``Authorization: Bearer <access_token>`` on every request
- On 401, attempts one refresh against ``/api/v1/auth/refresh`` and retries
- Maps the standard error envelope (``{"error": {"code", "message"}}``)
  to :class:`CLIError` with a stable ``exit_code``
- Surfaces a friendly "not authenticated" hint when keyring is empty

The refresh dance is intentionally bounded: ONE retry per request. If the
refresh itself returns 401, we surface that and stop — the user must
re-authenticate via ``kg auth login``.

Why not share this with the backend's ``httpx.AsyncClient``? Different
process model (sync CLI vs async web), different dependency surface
(the CLI is intentionally minimal). We duplicate the small mapping
table from ``backend/app/api/errors.py`` rather than couple the two
packages — a future "SDK" can be extracted if the duplication grows.
"""

from __future__ import annotations

from typing import Any

import httpx

# === Exit code catalog ===
# Stable across the CLI. Documented in the CLI plan under "Success Criteria"
# and in the help text emitted by `kg --help`.

EXIT_OK = 0
EXIT_AUTH = 1  # 401 (also refresh failed)
EXIT_NOT_FOUND = 2  # 404
EXIT_FORBIDDEN = 3  # 403
EXIT_RATE_LIMIT = 4  # 429
EXIT_GENERIC = 5  # anything else (server error, network error, bad request)

_STATUS_TO_EXIT: dict[int, int] = {
    400: EXIT_GENERIC,
    401: EXIT_AUTH,
    403: EXIT_FORBIDDEN,
    404: EXIT_NOT_FOUND,
    409: EXIT_GENERIC,
    422: EXIT_GENERIC,
    429: EXIT_RATE_LIMIT,
    500: EXIT_GENERIC,
    502: EXIT_GENERIC,
    503: EXIT_GENERIC,
    504: EXIT_GENERIC,
}


class CLIError(RuntimeError):
    """Raised by the client when the server returns an error envelope.

    Attributes:
        code: Stable error code from the API (E1-E15), or ``None`` for
            network/transport errors.
        status_code: HTTP status code (or ``None`` for network errors).
        exit_code: Numeric exit code per :data:`EXIT_*` constants.
        details: Optional structured context from the server envelope.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.exit_code = _STATUS_TO_EXIT.get(status_code or -1, EXIT_GENERIC)
        self.details = details or {}


# === Credential accessor protocol ===
# The client doesn't own credentials — it queries a tiny callback so the
# keyring layer can be swapped (file fallback, env var, in-memory for tests).

CredentialGetter = "Any"  # Callable[[], tuple[str, str] | None] — kept loose
# Returning ``None`` means "not logged in". Returning a tuple
# ``(access, refresh)`` injects Authorization and enables refresh.


def _noop_getter() -> tuple[str, str] | None:
    return None


# === Client ===


class KnowGateClient:
    """Thin sync wrapper around :class:`httpx.Client` for the KnowGate REST API.

    Args:
        base_url: API root (e.g., ``http://localhost:8000``).
        credential_getter: Callable returning ``(access_token, refresh_token)``
            or ``None`` if the user is not authenticated. Refresh tokens
            are stored alongside access tokens so we can call
            ``/api/v1/auth/refresh`` on a 401.
        timeout: HTTP request timeout in seconds (default 30).
    """

    def __init__(
        self,
        base_url: str,
        credential_getter: _CredentialGetter | None = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._creds = credential_getter or _noop_getter
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "knowgate-cli/0.1.0"},
        )

    def close(self) -> None:
        """Close the underlying HTTP client (idempotent)."""
        self._http.close()

    def __enter__(self) -> KnowGateClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # === HTTP methods ===

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, json_body=json)

    def patch(self, path: str, json: dict[str, Any] | None = None) -> Any:
        return self._request("PATCH", path, json_body=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    # === Core ===

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        _retried: bool = False,
    ) -> Any:
        """Issue a request with auth, refresh-once-on-401, and error mapping.

        On success returns the parsed JSON body, or ``None`` for 204/empty.
        On error raises :class:`CLIError` with a stable exit code.
        """
        if not path.startswith("/"):
            path = "/" + path
        # Normalize API path: accept both "/api/v1/..." and bare "auth/...".
        # Convention: callers always include the /api/v1 prefix; this is
        # purely defensive in case a future caller forgets.
        if not path.startswith("/api/"):
            path = "/api/v1" + path

        headers: dict[str, str] = {}
        creds = self._creds()
        if creds is not None:
            access, _refresh = creds
            headers["Authorization"] = f"Bearer {access}"

        try:
            response = self._http.request(
                method,
                path,
                params=params,
                json=json_body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise CLIError(
                f"Network error talking to {self.base_url}: {exc}",
            ) from exc

        # Refresh-and-retry exactly once on 401 (only if we have a refresh token)
        if response.status_code == 401 and not _retried:
            refreshed = self._try_refresh()
            if refreshed is not None:
                # _try_refresh updates the credential getter's underlying state
                # and returns the new access token. Retry the original request
                # with the fresh Authorization header.
                return self._request(
                    method,
                    path,
                    params=params,
                    json_body=json_body,
                    _retried=True,
                )

        return self._parse(response)

    def _try_refresh(self) -> str | None:
        """Attempt ``/api/v1/auth/refresh`` with the stored refresh token.

        Returns the new access token on success, ``None`` if the user
        is not authenticated or the refresh failed. The credential
        getter is expected to update its own state when the underlying
        token store is mutated; we just call it again to re-read.
        """
        creds = self._creds()
        if creds is None:
            return None
        _access, refresh = creds
        try:
            resp = self._http.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh},
            )
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        try:
            body = resp.json()
        except ValueError:
            return None
        new_access = body.get("access_token")
        new_refresh = body.get("refresh_token", refresh)
        if not new_access:
            return None
        # Hand the new pair back to the credential getter. The default
        # getter is a no-op, so this only takes effect for keyring/file
        # backends that implement the mutating protocol below.
        if hasattr(self._creds, "set_tokens"):
            self._creds.set_tokens(new_access, new_refresh)  # type: ignore[attr-defined]
        return new_access

    def _parse(self, response: httpx.Response) -> Any:
        """Parse response, raise :class:`CLIError` on non-2xx."""
        if response.status_code == 204 or not response.content:
            return None
        # Try to decode JSON; if the server returned a non-JSON body on an
        # error, treat it as a generic CLI error so the user still sees
        # the status code + text.
        try:
            body = response.json()
        except ValueError:
            if response.is_success:
                return response.text
            raise CLIError(
                f"HTTP {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            ) from None

        if response.is_success:
            return body

        # Standard error envelope: {"error": {"code", "message", "details?"}}
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            err = body["error"]
            raise CLIError(
                err.get("message") or "Request failed",
                code=err.get("code"),
                status_code=response.status_code,
                details=err.get("details"),
            )

        # Some FastAPI defaults still surface as {"detail": "..."}
        if isinstance(body, dict) and "detail" in body:
            raise CLIError(
                str(body["detail"]),
                status_code=response.status_code,
            )

        raise CLIError(
            f"HTTP {response.status_code}: {body}",
            status_code=response.status_code,
        )


# === Type alias for the credential getter ===
# Documented as a protocol-style Callable; we keep it loose (not a typing.Protocol)
# to avoid a hard dependency on `typing_extensions` and to make mocking trivial.

from collections.abc import Callable  # noqa: E402  — placed here for readability

_CredentialGetter = Callable[[], tuple[str, str] | None]


__all__ = [
    "EXIT_AUTH",
    "EXIT_FORBIDDEN",
    "EXIT_GENERIC",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_RATE_LIMIT",
    "CLIError",
    "KnowGateClient",
]
