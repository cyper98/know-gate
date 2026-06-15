"""Tests for the shared HTTP client + error envelope mapping."""

from __future__ import annotations

import httpx
import pytest

from knowgate_cli.client import (
    EXIT_AUTH,
    EXIT_FORBIDDEN,
    EXIT_GENERIC,
    EXIT_NOT_FOUND,
    EXIT_RATE_LIMIT,
    CLIError,
    KnowGateClient,
)


class TestExitCodeMapping:
    """Status code → exit code per the CLI plan §"Success Criteria"."""

    @pytest.mark.parametrize(
        "status_code,expected_exit",
        [
            (400, EXIT_GENERIC),
            (401, EXIT_AUTH),
            (403, EXIT_FORBIDDEN),
            (404, EXIT_NOT_FOUND),
            (409, EXIT_GENERIC),
            (422, EXIT_GENERIC),
            (429, EXIT_RATE_LIMIT),
            (500, EXIT_GENERIC),
            (503, EXIT_GENERIC),
        ],
    )
    def test_status_to_exit(self, status_code: int, expected_exit: int) -> None:
        err = CLIError("x", status_code=status_code)
        assert err.exit_code == expected_exit


class TestRequestMapping:
    """httpx response → CLIError with the right code + details."""

    def test_error_envelope_extracted(self, client: KnowGateClient, mock_http) -> None:
        mock_http.post("/api/v1/query").mock(
            return_value=httpx.Response(
                422,
                json={"error": {"code": "E2", "message": "Bad question"}},
            )
        )
        with pytest.raises(CLIError) as exc_info:
            client.post("/query", json={"question": "x"})
        assert exc_info.value.code == "E2"
        assert "Bad question" in str(exc_info.value)
        assert exc_info.value.status_code == 422

    def test_legacy_detail_envelope(self, client: KnowGateClient, mock_http) -> None:
        mock_http.post("/api/v1/query").mock(
            return_value=httpx.Response(404, json={"detail": "Not here"})
        )
        with pytest.raises(CLIError) as exc_info:
            client.post("/query", json={"question": "x"})
        assert "Not here" in str(exc_info.value)
        assert exc_info.value.status_code == 404

    def test_204_returns_none(self, client: KnowGateClient, mock_http) -> None:
        mock_http.delete("/api/v1/sources/abc").mock(return_value=httpx.Response(204))
        assert client.delete("/sources/abc") is None

    def test_2xx_returns_parsed_json(self, client: KnowGateClient, mock_http) -> None:
        mock_http.get("/api/v1/sources").mock(
            return_value=httpx.Response(200, json=[{"id": "1"}, {"id": "2"}])
        )
        rows = client.get("/sources")
        assert rows == [{"id": "1"}, {"id": "2"}]

    def test_path_prefix_added(self, client: KnowGateClient, mock_http) -> None:
        """Callers may pass bare 'query' or '/api/v1/query' interchangeably."""
        route = mock_http.post("/api/v1/query").mock(
            return_value=httpx.Response(200, json={"answer": "ok"})
        )
        body = client.post("/query", json={"question": "hi"})
        assert body == {"answer": "ok"}
        assert route.called


class TestAuthInjection:
    """Authorization header is attached when creds are present."""

    def test_no_creds_no_header(self, client: KnowGateClient, mock_http) -> None:
        route = mock_http.get("/api/v1/sources").mock(return_value=httpx.Response(200, json=[]))
        client.get("/sources")
        assert "Authorization" not in route.calls.last.request.headers

    def test_with_creds_attaches_bearer(self, mock_http) -> None:
        from knowgate_cli import auth as auth_mod

        creds = auth_mod._ActiveCredentials(
            api_url="http://test",
            email="u@e.com",
            creds=auth_mod.StoredCredentials(
                access_token="ACCESS",
                refresh_token="REFRESH",
                user={},
            ),
        )
        client = KnowGateClient(base_url="http://test", credential_getter=creds)
        route = mock_http.get("/api/v1/sources").mock(return_value=httpx.Response(200, json=[]))
        client.get("/sources")
        assert route.calls.last.request.headers["Authorization"] == "Bearer ACCESS"


class TestRefreshOn401:
    """On 401, the client tries to refresh and retries once."""

    def test_refresh_retry_succeeds(self, mock_http) -> None:
        from knowgate_cli import auth as auth_mod

        creds = auth_mod._ActiveCredentials(
            api_url="http://test",
            email="u@e.com",
            creds=auth_mod.StoredCredentials(
                access_token="OLD",
                refresh_token="OLDREFRESH",
                user={},
            ),
        )
        client = KnowGateClient(base_url="http://test", credential_getter=creds)
        # First call to /sources returns 401
        mock_http.get("/api/v1/sources").mock(
            side_effect=[
                httpx.Response(401, json={"detail": "expired"}),
                httpx.Response(200, json=[{"id": "ok"}]),
            ]
        )
        # Refresh succeeds
        mock_http.post("/api/v1/auth/refresh").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "NEW",
                    "refresh_token": "NEWREFRESH",
                },
            )
        )
        rows = client.get("/sources")
        assert rows == [{"id": "ok"}]
        # The new tokens were persisted back to the getter
        assert creds.creds is not None
        assert creds.creds.access_token == "NEW"
        assert creds.creds.refresh_token == "NEWREFRESH"

    def test_refresh_failure_does_not_retry(self, mock_http) -> None:
        from knowgate_cli import auth as auth_mod

        creds = auth_mod._ActiveCredentials(
            api_url="http://test",
            email="u@e.com",
            creds=auth_mod.StoredCredentials(
                access_token="OLD",
                refresh_token="OLDREFRESH",
                user={},
            ),
        )
        client = KnowGateClient(base_url="http://test", credential_getter=creds)
        # Original request: 401
        mock_http.get("/api/v1/sources").mock(
            return_value=httpx.Response(401, json={"detail": "expired"})
        )
        # Refresh also returns 401 — client should NOT retry the original
        mock_http.post("/api/v1/auth/refresh").mock(
            return_value=httpx.Response(401, json={"detail": "refresh expired"})
        )
        with pytest.raises(CLIError) as exc_info:
            client.get("/sources")
        # Error message should reflect the refresh failure
        assert exc_info.value.status_code == 401
