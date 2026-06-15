"""Tests for the query sub-command."""

from __future__ import annotations

import httpx
import pytest

from knowgate_cli.client import CLIError
from knowgate_cli.output import Output
from knowgate_cli.query import _read_question, run


class TestReadQuestion:
    """Question input resolution from the three sources."""

    def test_positional(self, tmp_path) -> None:
        assert _read_question("hello", None, False) == "hello"

    def test_strips_whitespace(self) -> None:
        assert _read_question("  hello  ", None, False) == "hello"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Question is empty"):
            _read_question("   ", None, False)

    def test_no_source_raises(self) -> None:
        with pytest.raises(ValueError, match="Provide a question"):
            _read_question(None, None, False)

    def test_two_sources_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="only one"):
            _read_question("a", tmp_path / "f", False)

    def test_file_source(self, tmp_path) -> None:
        f = tmp_path / "q.txt"
        f.write_text("file question")
        assert _read_question(None, f, False) == "file question"

    def test_file_missing_raises(self, tmp_path) -> None:
        f = tmp_path / "missing.txt"
        with pytest.raises(FileNotFoundError):
            _read_question(None, f, False)


class TestQueryRun:
    """The `run` function posts to /query and renders the response."""

    def test_post_payload_includes_question(self, client, mock_http) -> None:
        route = mock_http.post("/api/v1/query").mock(
            return_value=httpx.Response(
                200,
                json={
                    "query_id": "q1",
                    "answer": "Yes",
                    "citations": [],
                    "no_answer": False,
                    "latency_ms": 100,
                },
            )
        )
        out = Output(json_mode=True)
        body = run(client, out, question="What?")
        assert body["answer"] == "Yes"
        sent = route.calls.last.request
        import json as _json

        sent_body = _json.loads(sent.content)
        assert sent_body["question"] == "What?"

    def test_bypass_cache_flag_forwarded(self, client, mock_http) -> None:
        route = mock_http.post("/api/v1/query").mock(
            return_value=httpx.Response(200, json={"answer": "x", "citations": []})
        )
        out = Output(json_mode=True)
        run(client, out, question="q", bypass_cache=True)
        import json as _json

        sent_body = _json.loads(route.calls.last.request.content)
        assert sent_body.get("bypass_cache") is True

    def test_error_from_api_raises(self, client, mock_http) -> None:
        mock_http.post("/api/v1/query").mock(
            return_value=httpx.Response(
                429,
                json={"error": {"code": "E7", "message": "Slow down"}},
            )
        )
        out = Output()
        with pytest.raises(CLIError) as exc_info:
            run(client, out, question="q")
        assert exc_info.value.code == "E7"

    def test_no_result_renders_warning(self, client, mock_http) -> None:
        mock_http.post("/api/v1/query").mock(
            return_value=httpx.Response(
                200,
                json={
                    "query_id": "q1",
                    "answer": "",
                    "no_answer": True,
                    "no_result": {
                        "reason": "permission_denied",
                        "message": "No docs in your group",
                        "suggestions": ["Ask an admin"],
                        "denied_count": 5,
                    },
                    "citations": [],
                },
            )
        )
        # Just verify no exception; the human rendering is the spinner
        # + warning lines on stderr — we don't assert on those here.
        out = Output(json_mode=True)
        body = run(client, out, question="q")
        assert body["no_result"]["message"] == "No docs in your group"
