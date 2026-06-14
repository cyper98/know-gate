"""Unit tests for the hybrid search + RRF merge."""

from __future__ import annotations

from app.retrieval.hybrid_search import (
    SearchCandidate,
    merge_rrf,
)


def _cand(chunk_id: str, text: str = "x", score: float = 1.0) -> SearchCandidate:
    return SearchCandidate(chunk_id=chunk_id, doc_id="d1", text=text, score=score)


def test_merge_empty_inputs_returns_empty() -> None:
    assert merge_rrf([], []) == []


def test_merge_only_vector_results() -> None:
    """All candidates come from the vector retriever only."""
    vec = [_cand("a", "alpha"), _cand("b", "bravo")]
    out = merge_rrf(vec, [], top_k=10)
    assert [c.chunk_id for c in out] == ["a", "b"]
    assert all(c.retrieval_source == "vector" for c in out)


def test_merge_only_keyword_results() -> None:
    kw = [_cand("x", "xray"), _cand("y", "yankee")]
    out = merge_rrf([], kw, top_k=10)
    assert [c.chunk_id for c in out] == ["x", "y"]
    assert all(c.retrieval_source == "keyword" for c in out)


def test_merge_dedupes_chunks_in_both_lists() -> None:
    """A chunk present in BOTH lists gets marked 'both' (not duplicated)."""
    vec = [_cand("a"), _cand("b"), _cand("c")]
    kw = [_cand("b"), _cand("d")]
    out = merge_rrf(vec, kw, top_k=10)
    chunk_ids = [c.chunk_id for c in out]
    assert len(chunk_ids) == 4
    assert set(chunk_ids) == {"a", "b", "c", "d"}
    # b was in both lists
    b_cand = next(c for c in out if c.chunk_id == "b")
    assert b_cand.retrieval_source == "both"


def test_merge_higher_ranks_score_higher() -> None:
    """A chunk at rank 0 should score higher than rank 2 (same list)."""
    vec = [_cand("first"), _cand("second"), _cand("third")]
    out = merge_rrf(vec, [], top_k=10)
    assert out[0].chunk_id == "first"
    assert out[0].score > out[1].score > out[2].score


def test_merge_respects_top_k_cap() -> None:
    vec = [_cand(f"v{i}") for i in range(10)]
    kw = [_cand(f"k{i}") for i in range(10)]
    out = merge_rrf(vec, kw, top_k=5)
    assert len(out) == 5


def test_merge_hybrid_boosts_dual_list_chunks() -> None:
    """A chunk in BOTH lists should outrank one in just one list (at same rank)."""
    # 'shared' is at rank 0 in both; 'vector-only' is at rank 0 in vec only
    vec = [_cand("shared"), _cand("vector-only")]
    kw = [_cand("shared"), _cand("keyword-only")]
    out = merge_rrf(vec, kw, top_k=10)
    # shared gets 2 * 1/(60+1); others get 1 * 1/(60+1)
    shared_score = next(c.score for c in out if c.chunk_id == "shared")
    others = [c.score for c in out if c.chunk_id != "shared"]
    assert shared_score > max(others)


def test_merge_preserves_text_from_keyword_when_vector_has_empty() -> None:
    """If the vector retriever returns a candidate with no text and the
    keyword retriever has text for the same chunk, the merged candidate
    uses the keyword text."""
    vec = [SearchCandidate(chunk_id="x", doc_id="d1", text="", score=0.9)]
    kw = [SearchCandidate(chunk_id="x", doc_id="d1", text="hello world", score=0.5)]
    out = merge_rrf(vec, kw)
    assert out[0].text == "hello world"


def test_merge_rrf_score_uses_k_constant() -> None:
    """Different `k` values should change the score (sanity)."""
    vec = [_cand("a"), _cand("b")]
    kw = []
    out_k60 = merge_rrf(vec, kw, k=60)
    out_k10 = merge_rrf(vec, kw, k=10)
    # Same relative order, but k=10 gives higher absolute scores
    assert out_k10[0].score > out_k60[0].score


def test_candidate_to_payload_dict_shape() -> None:
    """The persisted shape (Query.retrieved_chunks) must be JSONB-safe."""
    c = SearchCandidate(
        chunk_id="c1",
        doc_id="d1",
        text="some text",
        score=0.5,
        retrieval_source="vector",
        section_title="Intro",
        page_number=2,
        language="en",
    )
    d = c.to_payload_dict()
    assert d["chunk_id"] == "c1"
    assert d["doc_id"] == "d1"
    assert d["score"] == 0.5
    assert d["retrieval_source"] == "vector"
    assert d["page_number"] == 2
    assert "text_preview" in d
