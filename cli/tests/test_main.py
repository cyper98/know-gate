"""End-to-end CLI tests via Typer's CliRunner.

These exercise the real :func:`app` entry point with respx-mocked
HTTP, focusing on:
- Global options are wired through (--api-url, --json, --verbose).
- Sub-commands hit the right endpoints and return the right exit codes.
- Error envelope mapping yields the documented exit code (1/2/3/4/5).
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from knowgate_cli.main import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestGlobalOptions:
    def test_help_prints(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "KnowGate CLI" in result.output

    def test_version_prints(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "kg " in result.output

    def test_subcommand_help(self, runner: CliRunner) -> None:
        for cmd in ("query", "source", "user", "auth", "config"):
            result = runner.invoke(app, [cmd, "--help"])
            assert result.exit_code == 0, f"{cmd} help failed: {result.output}"


class TestConfig:
    def test_list(self, runner: CliRunner, isolated_config_dir) -> None:
        result = runner.invoke(app, ["--json", "config", "list"])
        assert result.exit_code == 0
        body = json.loads(result.output)
        assert "api_url" in body
        assert body["api_url"] == "http://localhost:8000"

    def test_get_known(self, runner: CliRunner, isolated_config_dir) -> None:
        result = runner.invoke(app, ["config", "get", "api_url"])
        assert result.exit_code == 0
        assert "http://localhost:8000" in result.output

    def test_get_unknown_returns_2(self, runner: CliRunner, isolated_config_dir) -> None:
        result = runner.invoke(app, ["config", "get", "nope"])
        assert result.exit_code == 2

    def test_set_persists(self, runner: CliRunner, isolated_config_dir) -> None:
        result = runner.invoke(
            app,
            ["config", "set", "api_url", "http://x.test:1234"],
        )
        assert result.exit_code == 0
        # Read back via a second invocation
        result = runner.invoke(app, ["config", "get", "api_url"])
        assert "http://x.test:1234" in result.output


class TestQuery:
    def test_query_returns_0(self, runner: CliRunner, isolated_config_dir) -> None:
        with respx.mock(base_url="http://localhost:8000") as router:
            route = router.post("/api/v1/query").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "query_id": "q1",
                        "answer": "The answer is 42.",
                        "citations": [
                            {
                                "index": 1,
                                "chunk_id": "c1",
                                "doc_id": "d1",
                                "title": "Doc",
                                "source": "Drive",
                                "score": 0.9,
                            }
                        ],
                    },
                )
            )
            result = runner.invoke(
                app,
                ["--api-url", "http://localhost:8000", "--json", "query", "What is the answer?"],
            )
            assert result.exit_code == 0, result.output
            body = json.loads(result.output)
            assert body["answer"] == "The answer is 42."
            assert route.called

    def test_query_429_returns_exit_4(self, runner: CliRunner, isolated_config_dir) -> None:
        with respx.mock(base_url="http://localhost:8000") as router:
            router.post("/api/v1/query").mock(
                return_value=httpx.Response(
                    429,
                    json={"error": {"code": "E7", "message": "Slow down"}},
                )
            )
            result = runner.invoke(
                app,
                ["--api-url", "http://localhost:8000", "query", "x"],
            )
            assert result.exit_code == 4

    def test_query_401_returns_exit_1(self, runner: CliRunner, isolated_config_dir) -> None:
        with respx.mock(base_url="http://localhost:8000") as router:
            # /query → 401. No refresh attempt happens because the
            # default fixture has no creds, so the client surfaces the
            # original 401 (exit code 1 = auth).
            router.post("/api/v1/query").mock(
                return_value=httpx.Response(401, json={"detail": "nope"})
            )
            result = runner.invoke(
                app,
                ["--api-url", "http://localhost:8000", "query", "x"],
            )
            assert result.exit_code == 1

    def test_query_no_question_returns_2(self, runner: CliRunner, isolated_config_dir) -> None:
        result = runner.invoke(app, ["--api-url", "http://localhost:8000", "query"])
        assert result.exit_code == 2


class TestSourceFlow:
    def test_list(self, runner: CliRunner, isolated_config_dir) -> None:
        with respx.mock(base_url="http://localhost:8000") as router:
            router.get("/api/v1/sources").mock(return_value=httpx.Response(200, json=[]))
            result = runner.invoke(
                app,
                ["--api-url", "http://localhost:8000", "--json", "source", "list"],
            )
            assert result.exit_code == 0
            assert json.loads(result.output) == []


class TestUserFlow:
    def test_list(self, runner: CliRunner, isolated_config_dir) -> None:
        with respx.mock(base_url="http://localhost:8000") as router:
            router.get("/api/v1/users").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "u1",
                                "email": "a@e.com",
                                "display_name": "A",
                                "roles": ["admin"],
                                "status": "active",
                                "last_login_at": None,
                            }
                        ],
                        "meta": {"limit": 50, "next_cursor": None},
                    },
                )
            )
            result = runner.invoke(
                app,
                ["--api-url", "http://localhost:8000", "--json", "user", "list"],
            )
            assert result.exit_code == 0
            body = json.loads(result.output)
            assert body["data"][0]["email"] == "a@e.com"
