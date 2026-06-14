"""Retrieval + LLM pipeline (query side).

The user-facing query path:

    embed_query (cache)
        → hybrid_search (vector + keyword + RRF)
        → rerank (bge-reranker-v2-m3)
        → answer_generator (LLM + citation)
        → no_result handler (if zero candidates)

The pipeline is invoked by the query API endpoint. The retrieval
modules do not touch the API layer directly — they're called by
`app.retrieval.pipeline.run_query()` which handles the user-context
loading, query logging, and rate limiting.

Caching layers (Redis):
- Query embedding: 5 min TTL, keyed by sha256(query_text)
- LLM response (semantic): 24h TTL, keyed by sha256(query_text) + filter hash
"""

from app.retrieval.answer_generator import AnswerGenerator, GenerationResult
from app.retrieval.cache import SemanticCache, cache_key_for_query
from app.retrieval.hybrid_search import (
    HybridSearcher,
    SearchCandidate,
    merge_rrf,
    search_keyword,
    search_vector,
)
from app.retrieval.no_result import NoResultReason, build_no_result_message
from app.retrieval.pipeline import QueryPipeline, QueryResult, run_query
from app.retrieval.query_embedder import embed_query_cached
from app.retrieval.reranker import BGEReranker, RerankResult, rerank

__all__ = [
    "AnswerGenerator",
    "BGEReranker",
    "GenerationResult",
    "HybridSearcher",
    "NoResultReason",
    "QueryPipeline",
    "QueryResult",
    "RerankResult",
    "SearchCandidate",
    "SemanticCache",
    "build_no_result_message",
    "cache_key_for_query",
    "embed_query_cached",
    "merge_rrf",
    "rerank",
    "run_query",
    "search_keyword",
    "search_vector",
]
