"""Query pipeline orchestrator (end-to-end retrieval + LLM).

`run_query()` is the single entry point used by the API endpoint.
It composes:

  1. Detect query language (re-use `lang_detect.detect_language`)
  2. Check semantic cache → return on hit
  3. Embed the query (cache miss → bge-m3)
  4. Load user's access groups (permission filter)
  5. Hybrid search (vector + keyword + RRF)
  6. Rerank top candidates (bge-reranker-v2-m3)
  7. LLM answer generation with citations
  8. Resolve doc titles + presigned URLs for the citations
  9. Handle no-result / all-denied branches
 10. Persist the Query row (latency, cost, status)
 11. Set the semantic cache

The pipeline is async and never blocks the event loop on the
heavy ML parts (embed + rerank are run via `asyncio.to_thread`).

Permission defense in depth:
- The hybrid search layer filters by group_ids (SQL + Qdrant)
- The reranker + LLM only see the filtered candidates
- The citation builder never exposes a doc the user can't see
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import select

from app.audit.log import log_event
from app.db.enums import UserQueryStatus
from app.db.models import Document, Query, User
from app.db.session import get_session_factory
from app.logging import get_logger
from app.pipeline.lang_detect import detect_language
from app.retrieval.answer_generator import AnswerGenerator
from app.retrieval.cache import SemanticCache
from app.retrieval.citation_builder import Citation
from app.retrieval.hybrid_search import HybridSearcher, SearchCandidate
from app.retrieval.no_result import (
    NoResultReason,
    NoResultResponse,
    build_no_result_message,
)
from app.retrieval.query_embedder import embed_query_cached
from app.retrieval.reranker import BGEReranker

logger = get_logger(__name__)


# === Result type ===

@dataclass(slots=True)
class QueryResult:
    """Final result of one query run (returned to the API endpoint).

    The `cache_hit` flag tells the caller whether the result came
    from Redis (used for metrics + observability).
    """

    query_id: str
    answer: str
    citations: list[Citation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    no_answer: bool = False
    no_result: NoResultResponse | None = None
    latency_ms: int = 0
    cache_hit: bool = False
    llm_model: str | None = None
    cost_usd: float = 0.0
    status: str = "answered"  # UserQueryStatus value

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.no_result is not None:
            d["no_result"] = {
                "reason": self.no_result.reason.value,
                "message": self.no_result.message,
                "suggestions": self.no_result.suggestions or [],
                "denied_count": self.no_result.denied_count,
            }
        return d


# === Orchestrator ===

class QueryPipeline:
    """End-to-end query pipeline.

    Construct one per request (it's cheap; the heavy clients are
    process-local singletons). Or reuse across requests in tests.
    """

    def __init__(
        self,
        *,
        searcher: HybridSearcher | None = None,
        reranker: BGEReranker | None = None,
        generator: AnswerGenerator | None = None,
        cache: SemanticCache | None = None,
    ) -> None:
        self._searcher = searcher or HybridSearcher()
        self._reranker = reranker or BGEReranker()
        self._generator = generator or AnswerGenerator()
        self._cache = cache or SemanticCache()

    async def run(
        self,
        *,
        user_id: str,
        query_text: str,
        user_language: str | None = None,
        bypass_cache: bool = False,
    ) -> QueryResult:
        """Run the full pipeline. Returns a `QueryResult` ready to serialize.

        Args:
            user_id: the caller's UUID (for permission lookup + audit)
            query_text: the raw user question
            user_language: ISO 639-1 preferred by the user (overrides
                detection if provided)
            bypass_cache: set True to skip both the embed cache and
                the semantic cache (admin debug)
        """
        start = time.perf_counter()
        query_id = str(uuid.uuid4())

        if not query_text or not query_text.strip():
            return QueryResult(
                query_id=query_id,
                answer="",
                no_result=build_no_result_message(
                    NoResultReason.EMPTY_QUERY,
                    language=user_language or "en",
                ),
                no_answer=True,
                status=UserQueryStatus.NO_RESULT.value,
                latency_ms=_ms_since(start),
            )

        # 1. Resolve user (groups + email for audit)
        user = await _load_user(user_id)
        if user is None:
            # Unknown user — log and treat as no-permission
            logger.warning("query_unknown_user", user_id=user_id)
            return QueryResult(
                query_id=query_id,
                answer="",
                no_answer=True,
                status=UserQueryStatus.PERMISSION_DENIED.value,
                latency_ms=_ms_since(start),
            )

        # 2. Detect language (prefer user pref, fall back to detection)
        language = user_language or user.language_pref or "en"
        if not user_language:
            detected = detect_language(query_text)
            if detected != "und":
                language = detected

        group_ids = [str(g.id) for g in user.groups]

        # 3. Semantic cache check
        if not bypass_cache:
            cached = await self._cache.get(
                query_text, group_ids=group_ids, language=language
            )
            if cached is not None:
                cached["cache_hit"] = True
                cached["query_id"] = cached.get("query_id") or query_id
                return QueryResult(**{k: v for k, v in cached.items() if k in _QUERY_RESULT_FIELDS})

        # 4. Embed the query
        try:
            query_vector = await embed_query_cached(query_text, use_cache=not bypass_cache)
        except Exception as e:
            logger.exception("query_embed_failed", error=str(e))
            return QueryResult(
                query_id=query_id,
                answer="",
                no_answer=True,
                warnings=["embed_failed"],
                status=UserQueryStatus.FAILED.value,
                latency_ms=_ms_since(start),
            )

        # 5. Hybrid search
        candidates = await self._searcher.search(
            query_text, query_vector, group_ids=group_ids
        )

        if not candidates:
            # No candidates — distinguish "nothing" from "all denied".
            # If the user is in no groups at all → ALL_DENIED with count=0.
            # Otherwise → NO_RESULTS.
            reason = (
                NoResultReason.ALL_DENIED
                if not group_ids
                else NoResultReason.NO_RESULTS
            )
            no_result = build_no_result_message(reason, language=language)
            latency = _ms_since(start)
            await _log_query(
                query_id=query_id,
                user_id=user_id,
                query_text=query_text,
                query_language=language,
                retrieved_chunks=[],
                answer_text=None,
                confidence=None,
                warnings=["no_candidates"],
                status=UserQueryStatus.NO_RESULT.value,
                latency_ms=latency,
                cost_usd=0.0,
                llm_model=None,
            )
            result = QueryResult(
                query_id=query_id,
                answer="",
                no_result=no_result,
                no_answer=True,
                warnings=["no_candidates"],
                status=UserQueryStatus.NO_RESULT.value,
                latency_ms=latency,
            )
            await self._cache.set(query_text, group_ids=group_ids, language=language, result=result)
            return result

        # 6. Rerank
        reranked = await self._reranker.arerank(query_text, candidates, top_k=5)
        top_candidates = [r.candidate for r in reranked]

        # 7. Resolve doc titles + URLs for citations (batched)
        doc_titles, doc_urls, doc_updated = await _resolve_doc_metadata(top_candidates)

        # 8. LLM answer generation
        try:
            gen = await self._generator.generate(
                query=query_text,
                language=language,
                candidates=top_candidates,
                doc_titles=doc_titles,
                doc_urls=doc_urls,
                doc_updated=doc_updated,
            )
        except Exception as e:
            logger.exception("query_llm_failed", error=str(e))
            latency = _ms_since(start)
            await _log_query(
                query_id=query_id,
                user_id=user_id,
                query_text=query_text,
                query_language=language,
                retrieved_chunks=[c.to_payload_dict() for c in top_candidates],
                answer_text=None,
                confidence=None,
                warnings=[f"llm_failed:{type(e).__name__}"],
                status=UserQueryStatus.FAILED.value,
                latency_ms=latency,
                cost_usd=0.0,
                llm_model=None,
            )
            return QueryResult(
                query_id=query_id,
                answer="",
                no_answer=True,
                warnings=[f"llm_failed:{type(e).__name__}"],
                status=UserQueryStatus.FAILED.value,
                latency_ms=latency,
            )

        # 9. Build the result
        latency = _ms_since(start)
        confidence = _confidence_from_score(top_candidates[0].score if top_candidates else 0.0)
        final_status = (
            UserQueryStatus.NO_RESULT.value
            if gen.no_answer
            else UserQueryStatus.ANSWERED.value
        )
        result = QueryResult(
            query_id=query_id,
            answer=gen.answer,
            citations=gen.citations,
            warnings=gen.warnings,
            no_answer=gen.no_answer,
            latency_ms=latency,
            cache_hit=False,
            llm_model=gen.llm_model,
            cost_usd=gen.cost_usd,
            status=final_status,
        )

        # 10. Persist the Query row
        await _log_query(
            query_id=query_id,
            user_id=user_id,
            query_text=query_text,
            query_language=language,
            retrieved_chunks=[c.to_payload_dict() for c in top_candidates],
            answer_text=gen.answer or None,
            confidence=confidence,
            warnings=gen.warnings,
            status=final_status,
            latency_ms=latency,
            cost_usd=gen.cost_usd,
            llm_model=gen.llm_model,
        )

        # 11. Best-effort audit log
        import asyncio
        asyncio.create_task(
            log_event(
                actor_id=user_id,
                actor_email=user.email,
                action="query.execute",
                target_type="query",
                target_id=query_id,
                detail=f"status={final_status}, cost_usd={gen.cost_usd}, latency_ms={latency}",
            )
        )

        # 12. Cache the result
        await self._cache.set(query_text, group_ids=group_ids, language=language, result=result)

        return result


# === Module-level convenience ===

async def run_query(
    *,
    user_id: str,
    query_text: str,
    user_language: str | None = None,
    bypass_cache: bool = False,
) -> QueryResult:
    """Module-level convenience: build a pipeline + run it."""
    pipeline = QueryPipeline()
    return await pipeline.run(
        user_id=user_id,
        query_text=query_text,
        user_language=user_language,
        bypass_cache=bypass_cache,
    )


# === Helpers ===

_QUERY_RESULT_FIELDS = set(QueryResult.__dataclass_fields__.keys())  # type: ignore[attr-defined]


def _ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _confidence_from_score(score: float) -> str:
    """Map a top RRF score to a confidence label (heuristic)."""
    if score >= 0.05:
        return "high"
    if score >= 0.02:
        return "medium"
    return "low"


async def _load_user(user_id: str) -> User | None:
    """Load user + access groups. Returns None if missing or inactive."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None or user.status != "active":
            return None
        # Force-load the groups relationship (lazy="selectin" in model)
        _ = list(user.groups)
        return user


async def _resolve_doc_metadata(
    candidates: Sequence[SearchCandidate],
) -> tuple[dict[str, str], dict[str, str], dict[str, datetime]]:
    """Look up doc titles + presigned URLs for the top-N candidates."""
    if not candidates:
        return {}, {}, {}
    doc_ids = list({c.doc_id for c in candidates if c.doc_id})
    if not doc_ids:
        return {}, {}, {}

    factory = get_session_factory()
    async with factory() as session:
        rows = await session.execute(select(Document).where(Document.id.in_(doc_ids)))
        docs = list(rows.scalars())

    titles = {str(d.id): d.title for d in docs}
    updated = {
        str(d.id): d.updated_at
        for d in docs
        if d.updated_at is not None
    }
    # Presigned URLs: best-effort; do not block the response on MinIO
    # outage. Caller can fall back to a doc-list link.
    urls: dict[str, str] = {}
    try:
        from app.storage.uploader import get_presigned_url
        for d in docs:
            key = (d.extra or {}).get("object_key")
            if not key:
                continue
            url = await get_presigned_url(key, expires_seconds=3600)
            urls[str(d.id)] = url
    except Exception as e:
        logger.warning("presigned_url_failed", error=str(e))

    return titles, urls, updated


async def _log_query(
    *,
    query_id: str,
    user_id: str,
    query_text: str,
    query_language: str,
    retrieved_chunks: list[dict],
    answer_text: str | None,
    confidence: str | None,
    warnings: list[str],
    status: str,
    latency_ms: int,
    cost_usd: float,
    llm_model: str | None,
) -> None:
    """Insert the Query row. Best-effort (logs to stderr on DB failure)."""
    factory = get_session_factory()
    try:
        async with factory() as session:
            q = Query(
                id=query_id,
                user_id=user_id,
                query_text=query_text[:4000],  # cap to fit column
                query_language=query_language,
                expanded_queries=[],
                retrieved_chunks=retrieved_chunks,
                answer_text=answer_text[:16000] if answer_text else None,
                confidence=confidence,
                warnings=warnings,
                status=status,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                llm_model=llm_model,
            )
            session.add(q)
            await session.commit()
    except Exception:
        logger.exception("query_log_write_failed", query_id=query_id)


__all__ = ["QueryPipeline", "QueryResult", "run_query"]
