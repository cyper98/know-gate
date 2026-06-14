"""Unit tests for the citation builder."""

from __future__ import annotations

from datetime import UTC, datetime

from app.retrieval.citation_builder import (
    build_citations,
    extract_citation_indices,
)
from app.retrieval.hybrid_search import SearchCandidate


def _cand(
    chunk_id: str,
    doc_id: str = "d1",
    text: str = "text",
    payload: dict | None = None,
) -> SearchCandidate:
    return SearchCandidate(
        chunk_id=chunk_id, doc_id=doc_id, text=text, payload=payload or {}
    )


def test_extract_citation_indices_parses_tokens() -> None:
    """[1], [2], [10] should all be parsed correctly."""
    assert extract_citation_indices("See [1] and [10] and [2].") == [1, 10, 2]


def test_extract_citation_indices_no_tokens() -> None:
    assert extract_citation_indices("plain text without citations") == []


def test_extract_citation_indices_handles_empty() -> None:
    assert extract_citation_indices("") == []
    assert extract_citation_indices(None) == []  # type: ignore[arg-type]


def test_build_citations_preserves_index_order() -> None:
    candidates = [
        _cand("c1", payload={"source": "google_drive", "source_id": "f1"}),
        _cand("c2", payload={"source": "notion", "source_id": "p1"}),
    ]
    answer = "The answer cites [1] and [2]."
    citations, _ = build_citations(candidates, answer, doc_titles={"d1": "Doc 1"})
    assert [c.citation_index for c in citations] == [1, 2]
    assert [c.chunk_id for c in citations] == ["c1", "c2"]


def test_build_citations_enriches_with_titles() -> None:
    candidates = [_cand("c1"), _cand("c2")]
    answer = "[1] and [2]"
    citations, _ = build_citations(
        candidates,
        answer,
        doc_titles={"d1": "The Title"},
        doc_urls={"d1": "https://example.com/doc"},
    )
    assert all(c.title == "The Title" for c in citations)
    assert all(c.url == "https://example.com/doc" for c in citations)


def test_build_citations_enriches_with_updated_at() -> None:
    ts = datetime(2026, 6, 1, tzinfo=UTC)
    candidates = [_cand("c1")]
    answer = "[1]"
    citations, _ = build_citations(
        candidates, answer, doc_updated={"d1": ts}
    )
    assert citations[0].updated_at is not None
    assert "2026-06-01" in citations[0].updated_at


def test_build_citations_reports_ignored_out_of_range() -> None:
    """If the LLM says [5] but there are only 2 candidates, that's flagged."""
    candidates = [_cand("c1"), _cand("c2")]
    answer = "See [1] and [5] for details."
    _, extraction = build_citations(candidates, answer)
    assert 1 in extraction.unique_indices
    assert 5 in extraction.ignored_indices


def test_build_citations_unique_indices_are_deduped() -> None:
    """[1] [1] [2] should yield {1, 2}."""
    candidates = [_cand("c1"), _cand("c2")]
    answer = "[1] [1] [2]"
    _, extraction = build_citations(candidates, answer)
    assert extraction.unique_indices == [1, 2]


def test_build_citations_returns_snippet() -> None:
    long_text = "x" * 1000
    candidates = [_cand("c1", text=long_text)]
    answer = "[1]"
    citations, _ = build_citations(candidates, answer)
    assert citations[0].snippet is not None
    assert len(citations[0].snippet) == 200  # truncated


def test_build_citations_handles_no_answer() -> None:
    """If the LLM used no [N] tokens, the citation list is still built but empty."""
    candidates = [_cand("c1"), _cand("c2")]
    answer = "I could not find relevant information in the available sources."
    citations, extraction = build_citations(candidates, answer)
    assert len(citations) == 2  # candidates still present
    assert extraction.unique_indices == []
