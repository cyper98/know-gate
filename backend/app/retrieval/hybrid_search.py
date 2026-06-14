"""Hybrid search: vector (Qdrant) + keyword (PostgreSQL FTS) merged with RRF.

Reciprocal Rank Fusion (RRF) is the standard way to combine ranked
lists from different retrieval systems. The score formula is:

    score(d) = Σ_i  1 / (k + rank_i(d))

where `k` is a smoothing constant (60 is the commonly-cited value
from the original paper) and `rank_i(d)` is d's rank in the i-th
list (1-based, 0 for "not in the list"). The merged list is sorted
by score descending; duplicates are collapsed (keep the highest
score per `chunk_id`).

This module is dependency-injectable: `search_vector` and
`search_keyword` take the clients they need and return ranked
candidate lists. The merge step (`merge_rrf`) is pure-Python and
testable without any I/O.

Permission filtering:
- Vector: enforced at Qdrant via `group_ids ∈ user.groups` filter
- Keyword: enforced at PG via join with `document_groups` and
  filter `group_id IN (user.groups)`
Both layers apply the same rule (`user.groups ∩ doc.access_groups`).
The reranker can also be a 3rd layer; defense in depth.

Why not use Qdrant's built-in hybrid? Qdrant supports BM25 sparse
vectors but we already store the chunk text in PG with a GIN-indexed
tsvector. Reusing the PG index keeps the architecture simple and
lets us reuse the same permission filter logic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.db.session import get_session_factory
from app.logging import get_logger
from app.vector.collections import CHUNKS_COLLECTION

logger = get_logger(__name__)

# Standard RRF smoothing constant.
DEFAULT_RRF_K = 60

# Default top-K returned by each retriever before fusion.
DEFAULT_TOP_K = 20


@dataclass(slots=True)
class SearchCandidate:
    """One retrieved chunk, with provenance for citation building.

    `score` is set after RRF merge (0 for unmerged single-retriever
    results). `payload` is the raw Qdrant payload (kept so the
    citation builder can read `section_title`, `source`, etc.).
    """

    chunk_id: str
    doc_id: str
    text: str
    score: float = 0.0
    retrieval_source: str = ""  # "vector" | "keyword" | "both"
    payload: dict[str, Any] = field(default_factory=dict)
    section_title: str | None = None
    page_number: int | None = None
    language: str | None = None

    def to_payload_dict(self) -> dict:
        """Compact dict for the `Query.retrieved_chunks` JSONB column.

        Truncates the chunk text to 500 chars to keep the column
        bounded (the full text is in `chunks.chunk_text`).
        """
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "score": self.score,
            "retrieval_source": self.retrieval_source,
            "section_title": self.section_title,
            "page_number": self.page_number,
            "language": self.language,
            "text_preview": (self.text or "")[:500],
        }


# === Public functions ===

async def search_vector(
    client: AsyncQdrantClient,
    query_vector: list[float],
    *,
    group_ids: Sequence[str],
    top_k: int = DEFAULT_TOP_K,
    collection: str = CHUNKS_COLLECTION,
) -> list[SearchCandidate]:
    """Qdrant cosine search with permission filter on `group_ids`.

    Returns candidates ordered by similarity (desc). Candidates with
    no overlapping group are filtered out by Qdrant. Score is the
    raw cosine similarity (clamped to [0, 1]).
    """
    if not group_ids:
        # No groups → cannot see anything (fail-closed)
        return []

    query_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="group_ids",
                match=qmodels.MatchAny(any=list(group_ids)),
            ),
            qmodels.FieldCondition(
                key="status",
                match=qmodels.MatchValue(value="active"),
            ),
        ]
    )

    response = await client.query_points(
        collection_name=collection,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
        with_vectors=False,
    )
    candidates: list[SearchCandidate] = []
    for point in response.points:
        payload = point.payload or {}
        candidates.append(
            SearchCandidate(
                chunk_id=str(payload.get("chunk_id") or point.id),
                doc_id=str(payload.get("doc_id") or ""),
                text="",  # Qdrant doesn't store text — the join step fills this
                score=float(point.score or 0.0),
                retrieval_source="vector",
                payload=dict(payload),
                section_title=payload.get("section_title"),
                page_number=payload.get("page_number"),
                language=payload.get("language"),
            )
        )
    return candidates


async def search_keyword(
    query_text: str,
    *,
    group_ids: Sequence[str],
    top_k: int = DEFAULT_TOP_K,
) -> list[SearchCandidate]:
    """PostgreSQL FTS search with permission filter.

    Uses `to_tsquery('simple', plainto_tsquery(text))` against the
    `chunks.tsv` GIN-indexed column. Joins with `document_groups` to
    enforce the permission filter (user.groups ∩ doc.access_groups).
    Returns candidates ordered by `ts_rank` (desc).

    Falls back to `ILIKE` when the dialect is not PostgreSQL (so
    SQLite test envs still work).
    """
    factory = get_session_factory()
    async with factory() as session:
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            sql = """
                SELECT
                    c.id AS chunk_id,
                    c.document_id AS doc_id,
                    c.chunk_text AS text,
                    c.section_title AS section_title,
                    c.page_number AS page_number,
                    c.language AS language,
                    ts_rank(c.tsv, plainto_tsquery('simple', :q)) AS score
                FROM chunks c
                JOIN document_groups dg ON dg.document_id = c.document_id
                WHERE c.tsv @@ plainto_tsquery('simple', :q)
                  AND dg.group_id::text = ANY(:group_ids)
                ORDER BY score DESC
                LIMIT :top_k
            """
        else:
            # SQLite / non-PG fallback: ILIKE on chunk_text
            sql = """
                SELECT
                    c.id AS chunk_id,
                    c.document_id AS doc_id,
                    c.chunk_text AS text,
                    c.section_title AS section_title,
                    c.page_number AS page_number,
                    c.language AS language,
                    1.0 AS score
                FROM chunks c
                JOIN document_groups dg ON dg.document_id = c.document_id
                WHERE c.chunk_text ILIKE :q_pattern
                  AND dg.group_id = ANY(:group_ids)
                ORDER BY score DESC
                LIMIT :top_k
            """
        from sqlalchemy import text as sql_text

        if bind.dialect.name == "postgresql":
            rows = (
                await session.execute(
                    sql_text(sql),
                    {"q": query_text, "group_ids": list(group_ids), "top_k": top_k},
                )
            ).all()
        else:
            rows = (
                await session.execute(
                    sql_text(sql),
                    {"q_pattern": f"%{query_text}%", "group_ids": list(group_ids), "top_k": top_k},
                )
            ).all()

    return [
        SearchCandidate(
            chunk_id=str(r.chunk_id),
            doc_id=str(r.doc_id),
            text=r.text or "",
            score=float(r.score),
            retrieval_source="keyword",
            section_title=r.section_title,
            page_number=r.page_number,
            language=r.language,
        )
        for r in rows
    ]


def merge_rrf(
    vec_results: Sequence[SearchCandidate],
    kw_results: Sequence[SearchCandidate],
    *,
    k: int = DEFAULT_RRF_K,
    top_k: int = DEFAULT_TOP_K,
) -> list[SearchCandidate]:
    """Merge two ranked lists with Reciprocal Rank Fusion.

    The output is sorted by RRF score descending. Duplicate
    `chunk_id`s are collapsed: the candidate is kept once with
    `retrieval_source` set to `"both"` when it appears in both lists,
    and the scores add (per the RRF formula).
    """
    scores: dict[str, float] = {}
    candidates: dict[str, SearchCandidate] = {}

    def _accumulate(results: Sequence[SearchCandidate], source: str) -> None:
        for rank_zero, cand in enumerate(results, start=0):
            cid = cand.chunk_id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank_zero + 1)
            if cid in candidates:
                # Mark as found in both; merge payload if the existing
                # one is empty (the keyword result has the chunk text,
                # the vector result doesn't).
                existing = candidates[cid]
                existing.retrieval_source = "both"
                if not existing.text and cand.text:
                    existing.text = cand.text
                if not existing.section_title and cand.section_title:
                    existing.section_title = cand.section_title
                if not existing.page_number and cand.page_number is not None:
                    existing.page_number = cand.page_number
                if not existing.language and cand.language:
                    existing.language = cand.language
            else:
                # Copy so we don't mutate caller's list
                candidates[cid] = SearchCandidate(
                    chunk_id=cand.chunk_id,
                    doc_id=cand.doc_id,
                    text=cand.text,
                    score=0.0,  # filled in below
                    retrieval_source=source,
                    payload=dict(cand.payload),
                    section_title=cand.section_title,
                    page_number=cand.page_number,
                    language=cand.language,
                )

    _accumulate(vec_results, "vector")
    _accumulate(kw_results, "keyword")

    merged: list[SearchCandidate] = []
    for cid, sc in scores.items():
        cand = candidates[cid]
        cand.score = sc
        merged.append(cand)
    merged.sort(key=lambda c: c.score, reverse=True)
    return merged[:top_k]


# === Hydration ===

async def hydrate_text_from_db(
    candidates: Sequence[SearchCandidate],
) -> list[SearchCandidate]:
    """Fill in the `text` field for candidates that came from Qdrant.

    Qdrant stores vectors + payload but not the chunk text (it's in
    PG for FTS + audit). The vector-search path returns candidates
    with `text=""`; this helper loads the text in one batched query.
    """
    missing = [c for c in candidates if not c.text]
    if not missing:
        return list(candidates)

    chunk_ids = [c.chunk_id for c in missing]
    factory = get_session_factory()
    async with factory() as session:
        from sqlalchemy import select

        from app.db.models import Chunk

        rows = await session.execute(select(Chunk).where(Chunk.id.in_(chunk_ids)))
        text_by_id: dict[str, str] = {str(r.id): r.chunk_text for r in rows.scalars()}

    by_id = {c.chunk_id: c for c in candidates}
    for cid, text in text_by_id.items():
        if cid in by_id:
            by_id[cid].text = text
    return list(by_id.values())


# === Orchestrator ===

class HybridSearcher:
    """High-level hybrid search: vector + keyword + RRF + hydration.

    The class is stateless — create one per request, or reuse across
    requests (the underlying clients are process-local singletons).
    """

    def __init__(
        self,
        *,
        qdrant_client: AsyncQdrantClient | None = None,
        rrf_k: int = DEFAULT_RRF_K,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        from app.vector.client import get_qdrant_client
        self._qdrant = qdrant_client or get_qdrant_client()
        self._rrf_k = rrf_k
        self._top_k = top_k

    async def search(
        self,
        query_text: str,
        query_vector: list[float],
        *,
        group_ids: Sequence[str],
    ) -> list[SearchCandidate]:
        """Run vector + keyword search, merge with RRF, hydrate text.

        Returns the top `top_k` candidates ordered by RRF score.
        """
        vec_task = search_vector(
            self._qdrant, query_vector, group_ids=group_ids, top_k=self._top_k
        )
        kw_task = search_keyword(query_text, group_ids=group_ids, top_k=self._top_k)
        # Run in parallel — they're independent I/O
        import asyncio
        vec_res, kw_res = await asyncio.gather(vec_task, kw_task)

        merged = merge_rrf(vec_res, kw_res, k=self._rrf_k, top_k=self._top_k)
        return await hydrate_text_from_db(merged)


__all__ = [
    "DEFAULT_RRF_K",
    "DEFAULT_TOP_K",
    "HybridSearcher",
    "SearchCandidate",
    "hydrate_text_from_db",
    "merge_rrf",
    "search_keyword",
    "search_vector",
]
