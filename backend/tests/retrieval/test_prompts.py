"""Unit tests for the prompt builder."""

from __future__ import annotations

from app.llm.prompts import (
    KG_PROMPT_VERSION,
    build_answer_prompt,
)


def test_prompt_version_is_a_semver_string() -> None:
    """Version is used as a cache key prefix; keep it stable."""
    parts = KG_PROMPT_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_build_answer_prompt_returns_two_messages() -> None:
    """system + user (the standard chat-completion shape)."""
    chunks = [{"citation_index": 1, "text": "hello"}]
    msgs = build_answer_prompt(
        chunks=chunks, question="hi?", language="en"
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_build_answer_prompt_renders_citation_numbers() -> None:
    """Each chunk must show its [N] in the user prompt."""
    chunks = [
        {"citation_index": 1, "text": "alpha"},
        {"citation_index": 2, "text": "beta"},
    ]
    msgs = build_answer_prompt(
        chunks=chunks, question="?", language="en"
    )
    user = msgs[1]["content"]
    assert "[1]" in user
    assert "[2]" in user
    assert "alpha" in user
    assert "beta" in user


def test_build_answer_prompt_includes_language() -> None:
    """The language code goes in the prompt so the LLM knows what to answer in."""
    msgs = build_answer_prompt(
        chunks=[{"citation_index": 1, "text": "x"}], question="?", language="vi"
    )
    assert "vi" in msgs[1]["content"]


def test_build_answer_prompt_includes_question() -> None:
    msgs = build_answer_prompt(
        chunks=[{"citation_index": 1, "text": "x"}], question="how does auth work?", language="en"
    )
    assert "how does auth work?" in msgs[1]["content"]


def test_build_answer_prompt_handles_empty_chunks() -> None:
    """A no-result build must not crash (downstream checks for no_answer)."""
    msgs = build_answer_prompt(chunks=[], question="?", language="en")
    assert len(msgs) == 2
    assert "(no sources)" in msgs[1]["content"]


def test_system_prompt_includes_citation_rule() -> None:
    """The system prompt must enforce citations and the no-answer rule."""
    msgs = build_answer_prompt(
        chunks=[{"citation_index": 1, "text": "x"}], question="?", language="en"
    )
    sys = msgs[0]["content"]
    # Sanity: contains key phrases the LLM must respect
    assert "numbered footnote" in sys or "cite" in sys.lower()
    assert "language" in sys.lower()
    # "only using" (rule 1)
    assert "ONLY using" in sys or "only using" in sys.lower()
