"""Unit tests for the Google Drive connector (mocked httpx)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.sources.base import (
    ConnectorAuthError,
    ConnectorRateLimitError,
)
from app.sources.google_drive import (
    GoogleDriveConnector,
    config_from_oauth_tokens,
    deserialize_config,
    serialize_config,
)

# === Test config ===

def _make_connector(**overrides) -> GoogleDriveConnector:
    cfg = {
        "access_token": "ya29.test-access",
        "refresh_token": "1//test-refresh",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "token_expires_at": int(datetime.now(UTC).timestamp()) + 3600,
    }
    cfg.update(overrides)
    return GoogleDriveConnector(source_id="src-1", config=cfg)


def _mock_response(status_code: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    resp.json = MagicMock(return_value=json_data or {})
    resp.content = b"{}" if json_data else b""
    resp.text = text or json.dumps(json_data or {})
    return resp


# === Constructor / config ===

def test_connector_stores_config() -> None:
    c = _make_connector()
    assert c.source_type == "google_drive"
    assert c.access_token == "ya29.test-access"
    assert c.refresh_token == "1//test-refresh"
    assert c.folder_id is None


def test_connector_optional_folder_id() -> None:
    c = _make_connector(folder_id="folder-abc")
    assert c.folder_id == "folder-abc"


def test_config_from_oauth_tokens_round_trip() -> None:
    cfg = config_from_oauth_tokens(
        access_token="a", refresh_token="r", client_id="id",
        client_secret="sec", expires_in=3600, folder_id="f1",
    )
    blob = serialize_config(cfg)
    out = deserialize_config(blob)
    assert out["access_token"] == "a"
    assert out["refresh_token"] == "r"
    assert out["folder_id"] == "f1"
    # token_expires_at should be ~now + 3600
    delta = out["token_expires_at"] - int(datetime.now(UTC).timestamp())
    assert 3590 < delta <= 3605


# === Token refresh ===

@pytest.mark.asyncio
async def test_ensure_token_fresh_skips_when_not_close_to_expiry() -> None:
    """Token expires in 1 hour → no refresh attempt."""
    c = _make_connector(
        token_expires_at=int(datetime.now(UTC).timestamp()) + 3600
    )
    # _force_refresh would raise if called (it talks to Google)
    await c._ensure_token_fresh()  # should be a no-op


@pytest.mark.asyncio
async def test_ensure_token_fresh_refreshes_when_close_to_expiry() -> None:
    """Token expires in 60s (within the 5-minute grace) → refresh."""
    c = _make_connector(
        token_expires_at=int(datetime.now(UTC).timestamp()) + 60
    )
    # Mock _force_refresh to avoid hitting the network
    with patch.object(c, "_force_refresh", new=AsyncMock()) as mock:
        await c._ensure_token_fresh()
        mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_refresh_without_refresh_token_raises_auth_error() -> None:
    c = _make_connector(refresh_token=None)
    with pytest.raises(ConnectorAuthError, match="refresh token missing"):
        await c._force_refresh()


# === list_changes ===

@pytest.mark.asyncio
async def test_list_changes_first_sync_uses_start_page_token() -> None:
    c = _make_connector()
    start_resp = _mock_response(200, {"startPageToken": "100"})
    changes_resp = _mock_response(200, {
        "changes": [
            {
                "fileId": "file-1",
                "removed": False,
                "file": {
                    "id": "file-1",
                    "name": "doc.pdf",
                    "mimeType": "application/pdf",
                    "modifiedTime": "2026-06-14T10:00:00.000Z",
                    "size": "1024",
                    "webViewLink": "https://drive.google.com/file/d/file-1/view",
                },
            },
        ],
        "newStartPageToken": "200",
    })
    http_client = MagicMock()
    http_client.get = AsyncMock(side_effect=[start_resp, changes_resp])
    with (
        patch.object(c, "_http_client", new=AsyncMock(return_value=http_client)),
        patch.object(c, "_drive_get", new=AsyncMock(side_effect=[
            {"startPageToken": "100"},
            {"changes": changes_resp.json()["changes"], "newStartPageToken": "200"},
        ])),
    ):
        docs, next_cursor = await c.list_changes(cursor=None)
    assert len(docs) == 1
    assert docs[0].id == "file-1"
    assert docs[0].title == "doc.pdf"
    assert docs[0].size_bytes == 1024
    assert docs[0].is_deleted is False
    assert next_cursor == "200"


@pytest.mark.asyncio
async def test_list_changes_marks_trashed_as_deleted() -> None:
    c = _make_connector()
    with patch.object(c, "_drive_get", new=AsyncMock(return_value={
        "changes": [
            {"fileId": "file-deleted", "removed": True, "file": {"name": "gone.pdf"}},
        ],
        "newStartPageToken": "201",
    })):
        docs, _ = await c.list_changes(cursor="100")
    assert len(docs) == 1
    assert docs[0].is_deleted is True


@pytest.mark.asyncio
async def test_list_changes_raises_auth_error_on_403() -> None:
    c = _make_connector()
    with patch.object(c, "_http_client", new=AsyncMock()):  # noqa: SIM117
        with patch.object(c, "_force_refresh", new=AsyncMock()):
            with patch.object(c, "_http_client") as mock_client:
                resp = _mock_response(403, text="insufficient scope")
                mock_client.return_value.get = AsyncMock(return_value=resp)
                with pytest.raises(ConnectorAuthError):
                    await c._drive_get("/files", params={"pageSize": 1})


# === Error mapping ===

@pytest.mark.asyncio
async def test_drive_get_maps_429_to_rate_limit_error() -> None:
    c = _make_connector()
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": "30"}
    resp.text = "rate limited"
    client_mock = MagicMock()
    client_mock.get = AsyncMock(return_value=resp)
    with patch.object(c, "_http_client", new=AsyncMock(return_value=client_mock)):
        with pytest.raises(ConnectorRateLimitError) as exc:
            await c._drive_get("/files", params={"pageSize": 1})
        assert exc.value.retry_after == 30
