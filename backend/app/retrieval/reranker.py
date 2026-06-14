"""Reranker (bge-reranker-v2-m3 via sentence-transformers CrossEncoder).

After the hybrid retriever returns ~20 candidates, we rerank them
with a cross-encoder model that scores each (query, chunk) pair
jointly — far more accurate than the bi-encoder used for the first
stage, but too slow to run over the full corpus. Standard RAG
pattern.

The model is `BAAI/bge-reranker-v2-m3` (multilingual, same family
as the embedder). It returns a relevance score in roughly [-10, 10]
(logit). We sort descending and keep the top `top_k`.

Lazy model load (thread-safe singleton) — same pattern as the
ingest embedder. Pre-warm is exposed as `prewarm_reranker()` for the
worker startup hook.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from app.logging import get_logger
from app.retrieval.hybrid_search import SearchCandidate

logger = get_logger(__name__)

DEFAULT_MODEL_NAME = "BAAI/bge-reranker-v2-m3"
DEFAULT_TOP_K = 5
# Cap input to keep rerank latency predictable (bge-reranker-v2-m3
# is ~500ms for 20 pairs, but degrades to seconds past 100).
MAX_CANDIDATES = 50


# Thread-safe singleton (Celery prefork workers are threaded).
_lock = threading.Lock()
_model = None  # type: ignore[var-annotated]
_model_name: str | None = None


def _get_model(model_name: str = DEFAULT_MODEL_NAME):
    """Load the CrossEncoder model on first use, cached thereafter."""
    global _model, _model_name
    if _model is not None and _model_name == model_name:
        return _model

    with _lock:
        if _model is not None and _model_name == model_name:
            return _model

        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "sentence-transformers is not installed; "
                "pip install 'sentence-transformers>=3.2.0'"
            ) from e

        logger.info("reranker_loading", model=model_name)
        model = CrossEncoder(model_name, device=_resolve_device())
        # Warmup
        model.predict([("warmup query", "warmup passage")])

        _model = model
        _model_name = model_name
        logger.info("reranker_loaded", model=model_name)
        return _model


def _resolve_device() -> str:
    try:
        from app.config import get_settings
        return get_settings().embedding_device
    except Exception:  # pragma: no cover
        return "cpu"


def reset_for_tests() -> None:
    """Drop the cached model. Tests only."""
    global _model, _model_name
    with _lock:
        _model = None
        _model_name = None


@dataclass(slots=True)
class RerankResult:
    """One reranked candidate, with its cross-encoder score."""

    candidate: SearchCandidate
    score: float


def rerank(
    query: str,
    candidates: Sequence[SearchCandidate],
    *,
    top_k: int = DEFAULT_TOP_K,
    model_name: str = DEFAULT_MODEL_NAME,
    max_input: int = MAX_CANDIDATES,
) -> list[RerankResult]:
    """Rerank candidates by (query, chunk_text) cross-encoder score.

    Args:
        query: the user's question
        candidates: output of `HybridSearcher.search()`
        top_k: how many to return (default 5)
        model_name: override the default reranker
        max_input: cap the number of candidates we feed the model

    Returns:
        Top `top_k` candidates with `score` set to the cross-encoder
        logit. The input `candidates` is not mutated.
    """
    if not candidates:
        return []
    if not query.strip():
        # Nothing to rerank against — return the input as-is
        return [RerankResult(c, c.score) for c in candidates[:top_k]]

    truncated = list(candidates[:max_input])
    model = _get_model(model_name)

    # Build the (query, passage) pairs. Use the chunk text; fall back
    # to the section title if text is missing.
    pairs: list[tuple[str, str]] = []
    for c in truncated:
        passage = c.text or c.section_title or ""
        pairs.append((query, passage))

    scores = model.predict(pairs, show_progress_bar=False)

    # scores is an array-like of floats
    reranked: list[RerankResult] = []
    for cand, s in zip(truncated, scores, strict=True):
        reranked.append(RerankResult(candidate=cand, score=float(s)))
    reranked.sort(key=lambda r: r.score, reverse=True)
    return reranked[:top_k]


async def arerank(
    query: str,
    candidates: Sequence[SearchCandidate],
    *,
    top_k: int = DEFAULT_TOP_K,
) -> list[RerankResult]:
    """Async wrapper around `rerank` (runs the sync call in a thread)."""
    return await asyncio.to_thread(rerank, query, candidates, top_k=top_k)


def prewarm_reranker(model_name: str = DEFAULT_MODEL_NAME) -> None:
    """Load the reranker model into memory (worker startup hook)."""
    logger.info("reranker_prewarm_start", model=model_name)
    _get_model(model_name)
    logger.info("reranker_prewarm_done", model=model_name)


# === High-level wrapper class ===

class BGEReranker:
    """Convenience wrapper for the reranker (parallels `BGEEmbedder`)."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self._model_name = model_name

    def rerank(
        self,
        query: str,
        candidates: Sequence[SearchCandidate],
        *,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[RerankResult]:
        return rerank(query, candidates, top_k=top_k, model_name=self._model_name)

    async def arerank(
        self,
        query: str,
        candidates: Sequence[SearchCandidate],
        *,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[RerankResult]:
        return await arerank(query, candidates, top_k=top_k)


__all__ = [
    "DEFAULT_MODEL_NAME",
    "DEFAULT_TOP_K",
    "MAX_CANDIDATES",
    "BGEReranker",
    "RerankResult",
    "arerank",
    "prewarm_reranker",
    "rerank",
    "reset_for_tests",
]
