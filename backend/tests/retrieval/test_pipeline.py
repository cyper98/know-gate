"""Unit tests for the query pipeline (orchestrator).

Heavy deps (Qdrant, Redis, LLM, DB) are mocked. We assert the
orchestrator composes the right calls in the right order, handles
the no-result / all-denied branches, and persists the Query row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.enums import UserQueryStatus
from app.retrieval.hybrid_search import SearchCandidate
from app.retrieval.no_result import NoResultReason
from app.retrieval.pipeline import QueryPipeline, QueryResult, run_query


def _fake_user(*, user_id: str | None = None, lang: str = "en") -> MagicMock:
    u = MagicMock()
    u.id = user_id or str(uuid.uuid4())
    u.email = "user@test.local"
    u.status = "active"
    u.language_pref = lang
    u.groups = []  # empty by default — caller can override
    return u


def _fake_candidate(
    chunk_id: str | None = None,
    doc_id: str | None = None,
    score: float = 0.05,
    text: str = "sample text",
) -> SearchCandidate:
    return SearchCandidate(
        chunk_id=chunk_id or str(uuid.uuid4()),
        doc_id=doc_id or str(uuid.uuid4()),
        text=text,
        score=score,
        payload={"source": "google_drive", "source_id": "f1"},
    )


def _fake_session_with_user(user: MagicMock) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


# === Empty query ===

@pytest.mark.asyncio
async def test_empty_query_returns_no_result_message() -> None:
    pipeline = QueryPipeline()
    result = await pipeline.run(
        user_id=str(uuid.uuid4()), query_text="", user_language="en"
    )
    assert result.no_answer is True
    assert result.no_result is not None
    assert result.no_result.reason == NoResultReason.EMPTY_QUERY
    assert result.status == UserQueryStatus.NO_RESULT.value


# === Unknown user ===

@pytest.mark.asyncio
async def test_unknown_user_returns_permission_denied() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)

    with patch("app.retrieval.pipeline.get_session_factory") as mock_factory:
        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        pipeline = QueryPipeline()
        r = await pipeline.run(
            user_id=str(uuid.uuid4()), query_text="hi", user_language="en"
        )
    assert r.status == UserQueryStatus.PERMISSION_DENIED.value


# === Embed failure ===

@pytest.mark.asyncio
async def test_embed_failure_marks_failed() -> None:
    user = _fake_user()
    user.groups = []  # explicit
    session = _fake_session_with_user(user)

    with patch("app.retrieval.pipeline.get_session_factory") as mock_factory, \
         patch("app.retrieval.pipeline.embed_query_cached",
               new=AsyncMock(side_effect=RuntimeError("embed boom"))), \
         patch("app.retrieval.pipeline.SemanticCache") as mock_cache_cls:
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache_cls.return_value = mock_cache

        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        pipeline = QueryPipeline()
        r = await pipeline.run(
            user_id=str(user.id), query_text="hi", user_language="en"
        )

    assert r.status == UserQueryStatus.FAILED.value
    assert "embed_failed" in r.warnings


# === No candidates (all denied) ===

@pytest.mark.asyncio
async def test_no_candidates_with_no_groups_returns_all_denied() -> None:
    """User in zero groups → ALL_DENIED (fail-closed)."""
    user = _fake_user()
    user.groups = []  # no groups
    session = _fake_session_with_user(user)

    fake_vec = [0.0] * 1024
    with patch("app.retrieval.pipeline.get_session_factory") as mock_factory, \
         patch("app.retrieval.pipeline.embed_query_cached",
               new=AsyncMock(return_value=fake_vec)), \
         patch("app.retrieval.pipeline._load_user", new=AsyncMock(return_value=user)), \
         patch("app.retrieval.pipeline.HybridSearcher") as mock_searcher_cls, \
         patch("app.retrieval.pipeline.SemanticCache") as mock_cache_cls:
        mock_searcher = MagicMock()
        mock_searcher.search = AsyncMock(return_value=[])
        mock_searcher_cls.return_value = mock_searcher
        # No cache hit
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache_cls.return_value = mock_cache

        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        pipeline = QueryPipeline()
        r = await pipeline.run(
            user_id=str(user.id), query_text="hi", user_language="en"
        )

    assert r.no_answer is True
    assert r.no_result is not None
    assert r.no_result.reason == NoResultReason.ALL_DENIED
    assert r.status == UserQueryStatus.NO_RESULT.value


# === Happy path ===

@pytest.mark.asyncio
async def test_happy_path_runs_end_to_end() -> None:
    user = _fake_user()
    user.groups = [MagicMock(id=str(uuid.uuid4()))]
    session = _fake_session_with_user(user)

    cands = [_fake_candidate(score=0.08), _fake_candidate(score=0.04)]

    fake_doc = MagicMock()
    fake_doc.id = cands[0].doc_id
    fake_doc.title = "Doc 1"
    fake_doc.updated_at = datetime(2026, 6, 1, tzinfo=UTC)
    fake_doc.extra = {"object_key": "k"}

    async def _resolve_meta(cands_arg):
        return {cands[0].doc_id: "Doc 1"}, {cands[0].doc_id: "https://x"}, {
            cands[0].doc_id: datetime(2026, 6, 1, tzinfo=UTC)
        }

    fake_vec = [0.0] * 1024
    with patch("app.retrieval.pipeline.get_session_factory") as mock_factory, \
         patch("app.retrieval.pipeline.embed_query_cached",
               new=AsyncMock(return_value=fake_vec)), \
         patch("app.retrieval.pipeline._load_user", new=AsyncMock(return_value=user)), \
         patch("app.retrieval.pipeline._resolve_doc_metadata", new=_resolve_meta), \
         patch("app.retrieval.pipeline.HybridSearcher") as mock_searcher_cls, \
         patch("app.retrieval.pipeline.BGEReranker") as mock_reranker_cls, \
         patch("app.retrieval.pipeline.AnswerGenerator") as mock_gen_cls, \
         patch("app.retrieval.pipeline.SemanticCache") as mock_cache_cls:
        mock_searcher = MagicMock()
        mock_searcher.search = AsyncMock(return_value=cands)
        mock_searcher_cls.return_value = mock_searcher

        # Reranker returns RerankResult objects
        from app.retrieval.reranker import RerankResult
        mock_reranker = MagicMock()
        mock_reranker.arerank = AsyncMock(
            return_value=[RerankResult(c, c.score) for c in cands]
        )
        mock_reranker_cls.return_value = mock_reranker

        from app.retrieval.answer_generator import GenerationResult
        from app.retrieval.citation_builder import Citation
        mock_gen = MagicMock()
        mock_gen.generate = AsyncMock(
            return_value=GenerationResult(
                answer="The capital is Hanoi [1].",
                citations=[Citation(
                    citation_index=1,
                    chunk_id=cands[0].chunk_id,
                    doc_id=cands[0].doc_id,
                    title="Doc 1",
                    section_title="Intro",
                    page_number=None,
                    source=None,
                    source_id=None,
                    url=None,
                    updated_at=None,
                    language=None,
                )],
                llm_model="gpt-4o-mini",
                cost_usd=0.001,
                latency_ms=800,
            )
        )
        mock_gen_cls.return_value = mock_gen

        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache_cls.return_value = mock_cache

        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        pipeline = QueryPipeline()
        r = await pipeline.run(
            user_id=str(user.id), query_text="what is the capital?", user_language="en"
        )

    assert r.answer == "The capital is Hanoi [1]."
    assert r.status == UserQueryStatus.ANSWERED.value
    assert r.no_answer is False
    assert r.cache_hit is False
    assert r.llm_model == "gpt-4o-mini"
    assert r.cost_usd == 0.001
    assert len(r.citations) == 1
    assert r.citations[0].citation_index == 1


# === Cache hit ===

@pytest.mark.asyncio
async def test_cache_hit_skips_embed_and_search() -> None:
    user = _fake_user()
    user.groups = [MagicMock(id=str(uuid.uuid4()))]
    session = _fake_session_with_user(user)

    cached = {
        "query_id": str(uuid.uuid4()),
        "answer": "cached answer [1]",
        "citations": [],
        "warnings": [],
        "no_answer": False,
        "no_result": None,
        "latency_ms": 5,
        "cache_hit": True,
        "llm_model": "gpt-4o-mini",
        "cost_usd": 0.0,
        "status": UserQueryStatus.ANSWERED.value,
    }
    with patch("app.retrieval.pipeline.get_session_factory") as mock_factory, \
         patch("app.retrieval.pipeline.embed_query_cached",
               new=AsyncMock()) as mock_embed, \
         patch("app.retrieval.pipeline._load_user", new=AsyncMock(return_value=user)), \
         patch("app.retrieval.pipeline.SemanticCache") as mock_cache_cls:
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=cached)
        mock_cache.set = AsyncMock()
        mock_cache_cls.return_value = mock_cache

        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        pipeline = QueryPipeline()
        r = await pipeline.run(
            user_id=str(user.id), query_text="cached query", user_language="en"
        )

    assert r.cache_hit is True
    assert r.answer == "cached answer [1]"
    # Embed was NOT called on cache hit
    mock_embed.assert_not_called()


# === LLM failure ===

@pytest.mark.asyncio
async def test_llm_failure_returns_failed_status() -> None:
    user = _fake_user()
    user.groups = [MagicMock(id=str(uuid.uuid4()))]
    session = _fake_session_with_user(user)

    cands = [_fake_candidate()]
    fake_vec = [0.0] * 1024
    with patch("app.retrieval.pipeline.get_session_factory") as mock_factory, \
         patch("app.retrieval.pipeline.embed_query_cached",
               new=AsyncMock(return_value=fake_vec)), \
         patch("app.retrieval.pipeline._load_user", new=AsyncMock(return_value=user)), \
         patch("app.retrieval.pipeline._resolve_doc_metadata",
               new=AsyncMock(return_value=({}, {}, {}))), \
         patch("app.retrieval.pipeline.HybridSearcher") as mock_searcher_cls, \
         patch("app.retrieval.pipeline.BGEReranker") as mock_reranker_cls, \
         patch("app.retrieval.pipeline.AnswerGenerator") as mock_gen_cls, \
         patch("app.retrieval.pipeline.SemanticCache") as mock_cache_cls:
        mock_searcher = MagicMock()
        mock_searcher.search = AsyncMock(return_value=cands)
        mock_searcher_cls.return_value = mock_searcher

        from app.retrieval.reranker import RerankResult
        mock_reranker = MagicMock()
        mock_reranker.arerank = AsyncMock(
            return_value=[RerankResult(c, c.score) for c in cands]
        )
        mock_reranker_cls.return_value = mock_reranker

        mock_gen = MagicMock()
        mock_gen.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
        mock_gen_cls.return_value = mock_gen

        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache_cls.return_value = mock_cache

        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        pipeline = QueryPipeline()
        r = await pipeline.run(
            user_id=str(user.id), query_text="hi", user_language="en"
        )

    assert r.status == UserQueryStatus.FAILED.value
    assert "llm_failed" in r.warnings[0]


# === Run module-level ===

@pytest.mark.asyncio
async def test_run_query_module_helper_returns_result() -> None:
    """The `run_query` convenience wraps `QueryPipeline().run()`."""
    user = _fake_user()
    user.groups = []
    session = _fake_session_with_user(user)

    with patch("app.retrieval.pipeline.get_session_factory") as mock_factory, \
         patch("app.retrieval.pipeline.embed_query_cached",
               new=AsyncMock(return_value=[0.0] * 1024)), \
         patch("app.retrieval.pipeline._load_user", new=AsyncMock(return_value=user)), \
         patch("app.retrieval.pipeline.HybridSearcher") as mock_searcher_cls, \
         patch("app.retrieval.pipeline.SemanticCache") as mock_cache_cls:
        mock_searcher = MagicMock()
        mock_searcher.search = AsyncMock(return_value=[])
        mock_searcher_cls.return_value = mock_searcher

        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache_cls.return_value = mock_cache

        mock_factory.return_value = MagicMock()
        mock_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_factory.return_value.return_value.__aexit__ = AsyncMock(return_value=None)

        r = await run_query(
            user_id=str(user.id), query_text="hi", user_language="en"
        )
    assert isinstance(r, QueryResult)
