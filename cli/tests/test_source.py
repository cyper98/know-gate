"""Tests for the source sub-commands."""

from __future__ import annotations

import json

import httpx
import pytest

from knowgate_cli.client import KnowGateClient
from knowgate_cli.output import Output
from knowgate_cli.source import (
    SOURCE_TYPES,
    create_source,
    delete_source,
    list_sources,
    show_source,
    sync_source,
)


@pytest.fixture()
def client() -> KnowGateClient:
    return KnowGateClient(base_url="http://test", credential_getter=lambda: None)


class TestListSources:
    def test_renders_rows_from_api(self, client, mock_http) -> None:
        mock_http.get("/api/v1/sources").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "abcdef1234567890",
                        "name": "Team Drive",
                        "type": "google_drive",
                        "status": "active",
                        "last_sync_at": "2026-06-15T10:00:00Z",
                        "last_error": None,
                    },
                ],
            )
        )
        out = Output(json_mode=True)
        rows = list_sources(client, out)
        assert rows[0]["name"] == "Team Drive"

    def test_empty_list_returns_empty(self, client, mock_http) -> None:
        mock_http.get("/api/v1/sources").mock(return_value=httpx.Response(200, json=[]))
        out = Output(json_mode=True)
        rows = list_sources(client, out)
        assert rows == []


class TestShowSource:
    def test_returns_single_row(self, client, mock_http) -> None:
        mock_http.get("/api/v1/sources/abc").mock(
            return_value=httpx.Response(
                200,
                json={"id": "abc", "name": "Drive", "type": "google_drive"},
            )
        )
        out = Output(json_mode=True)
        row = show_source(client, out, "abc")
        assert row["name"] == "Drive"


class TestSyncSource:
    def test_posts_to_sync_endpoint(self, client, mock_http) -> None:
        route = mock_http.post("/api/v1/sources/abc/sync").mock(
            return_value=httpx.Response(
                202,
                json={
                    "id": "job1",
                    "source_id": "abc",
                    "status": "queued",
                },
            )
        )
        out = Output(json_mode=True)
        body = sync_source(client, out, "abc")
        assert body["status"] == "queued"
        assert route.called


class TestDeleteSource:
    def test_with_yes_skips_confirm(self, client, mock_http) -> None:
        route = mock_http.delete("/api/v1/sources/abc").mock(return_value=httpx.Response(204))
        out = Output()  # no input needed when --yes
        delete_source(client, out, "abc", yes=True)
        assert route.called

    def test_without_yes_decline_returns_no_api_call(self, client, mock_http) -> None:
        # We deliberately do NOT register a DELETE route — the test
        # asserts that no API call is made. Mocking would also assert
        # the route was hit, which is the opposite of what we want.
        out = Output(color=False)
        delete_source(client, out, "abc", yes=False)
        # If we reach here without an unhandled exception, the
        # confirm-cancel path worked. (respx would raise if any other
        # request leaked past the mock transport.)


class TestCreateSource:
    def test_validates_type(self) -> None:
        out = Output()
        with pytest.raises(ValueError, match="Unknown source type"):
            create_source(client, out, source_type="bogus", name="x")

    def test_create_from_file_drive(self, client, mock_http, tmp_path) -> None:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps(
                {
                    "access_token": "AT",
                    "refresh_token": "RT",
                    "client_id": "CID",
                    "client_secret": "CSEC",
                    "token_expires_at": 0,
                }
            )
        )
        route = mock_http.post("/api/v1/sources").mock(
            return_value=httpx.Response(
                201,
                json={"id": "newsrc", "name": "My Drive", "type": "google_drive"},
            )
        )
        out = Output()
        body = create_source(
            client,
            out,
            name="My Drive",
            source_type="google_drive",
            from_file=cfg,
        )
        assert body["name"] == "My Drive"
        sent = route.calls.last.request
        sent_body = json.loads(sent.content)
        assert sent_body["type"] == "google_drive"
        assert sent_body["config"]["access_token"] == "AT"
        assert sent_body["name"] == "My Drive"

    def test_create_notion(self, client, mock_http, tmp_path) -> None:
        # We can't easily test the interactive prompts here, so use
        # from_file with a Notion config.
        cfg = tmp_path / "notion.json"
        cfg.write_text(
            json.dumps(
                {
                    "integration_token": "secret_NLP",
                    "root_page_ids": ["page-1"],
                }
            )
        )
        route = mock_http.post("/api/v1/sources").mock(
            return_value=httpx.Response(
                201,
                json={"id": "ns1", "name": "Wiki", "type": "notion"},
            )
        )
        out = Output()
        create_source(
            client,
            out,
            name="Wiki",
            source_type="notion",
            from_file=cfg,
        )
        sent_body = json.loads(route.calls.last.request.content)
        assert sent_body["type"] == "notion"
        assert sent_body["config"]["integration_token"] == "secret_NLP"


def test_source_types_constant() -> None:
    """The known source types tuple stays in sync with the backend enum."""
    assert "google_drive" in SOURCE_TYPES
    assert "notion" in SOURCE_TYPES
