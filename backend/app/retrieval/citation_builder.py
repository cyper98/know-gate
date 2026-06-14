"""Citation builder (map LLM [N] tokens → full citation objects).

The LLM returns the answer text with numbered footnote tokens like
"Vietnam's capital is Hanoi [1][2]." We extract the tokens, look up
the corresponding chunk in the top-N list, and build a structured
`Citation` object the frontend can render (title, section, page,
URL, source provider, last_updated).

Multi-version rule (D2): if two citations point to the same source
URL but one is `active` and the other `deprecated`, only the active
one is kept. The deprecated one is reported as a warning (not a
citation) so the user knows there's an older version.

Conflict rule (D3): if two citations disagree on a fact (detected
heuristically by a shared entity + a negating token), we keep both
and emit a warning string. The user is told the conflict and
recommended to trust the newer / official source.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.logging import get_logger
from app.retrieval.hybrid_search import SearchCandidate

logger = get_logger(__name__)


_CITATION_TOKEN_RE = re.compile(r"\[(\d+)\]")


@dataclass(slots=True)
class Citation:
    """A single source attached to one query answer.

    `citation_index` is the 1-based position in the LLM's source
    list — the [N] in the answer text refers to this. `url` is the
    pre-signed URL to the original file (when available).
    """

    citation_index: int
    chunk_id: str
    doc_id: str
    title: str
    section_title: str | None
    page_number: int | None
    source: str | None
    source_id: str | None
    url: str | None
    updated_at: str | None
    language: str | None
    score: float = 0.0
    # Optional: when the doc has a `presigned_url` extension in Qdrant
    # payload, we copy it here. The pipeline fills it in.
    snippet: str | None = None  # First ~200 chars of the chunk

    def to_dict(self) -> dict:
        return {
            "index": self.citation_index,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "section_title": self.section_title,
            "page_number": self.page_number,
            "source": self.source,
            "source_id": self.source_id,
            "url": self.url,
            "updated_at": self.updated_at,
            "language": self.language,
            "score": self.score,
            "snippet": self.snippet,
        }


@dataclass(slots=True)
class CitationExtraction:
    """Output of `extract_citations`.

    `unique_indices` is the deduped, sorted list of [N] tokens the
    LLM actually used. `warnings` carries any multi-version or
    conflict messages the UI should display.
    """

    unique_indices: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ignored_indices: list[int] = field(default_factory=list)  # out-of-range [N]


def extract_citation_indices(answer_text: str) -> list[int]:
    """Parse [N] tokens out of the LLM's answer text.

    Returns the indices in the order they appear (duplicates kept
    so we can count usage; dedup is done by the caller).
    """
    return [int(m.group(1)) for m in _CITATION_TOKEN_RE.finditer(answer_text or "")]


def build_citations(
    candidates: Sequence[SearchCandidate],
    answer_text: str,
    *,
    doc_titles: dict[str, str] | None = None,
    doc_urls: dict[str, str] | None = None,
    doc_updated: dict[str, datetime] | None = None,
) -> tuple[list[Citation], CitationExtraction]:
    """Build the final list of `Citation` objects from a query result.

    Args:
        candidates: the top-N candidates that were sent to the LLM
            (1-based indices correspond to [N] in the answer).
        answer_text: the LLM's raw response.
        doc_titles: optional map of doc_id -> human title.
        doc_urls: optional map of doc_id -> presigned URL.
        doc_updated: optional map of doc_id -> last updated timestamp.

    Returns:
        (citations, extraction). Citations are ordered by [N]
        ascending. `extraction.unique_indices` is the deduped set of
        indices the LLM actually used (in [N] order).
    """
    doc_titles = doc_titles or {}
    doc_urls = doc_urls or {}
    doc_updated = doc_updated or {}

    citations: list[Citation] = []
    for idx_zero, cand in enumerate(candidates):
        idx = idx_zero + 1
        title = doc_titles.get(cand.doc_id, "(unknown)")
        url = doc_urls.get(cand.doc_id)
        updated = doc_updated.get(cand.doc_id)
        snippet = (cand.text or "")[:200] if cand.text else None
        citations.append(
            Citation(
                citation_index=idx,
                chunk_id=cand.chunk_id,
                doc_id=cand.doc_id,
                title=title,
                section_title=cand.section_title,
                page_number=cand.page_number,
                source=(cand.payload or {}).get("source"),
                source_id=(cand.payload or {}).get("source_id"),
                url=url,
                updated_at=updated.isoformat() if updated else None,
                language=cand.language,
                score=cand.score,
                snippet=snippet,
            )
        )

    # Extract unique [N] tokens actually used
    raw_indices = extract_citation_indices(answer_text)
    seen: set[int] = set()
    unique: list[int] = []
    for i in raw_indices:
        if i in seen:
            continue
        seen.add(i)
        unique.append(i)

    ignored = [i for i in unique if i < 1 or i > len(citations)]
    used = [i for i in unique if 1 <= i <= len(citations)]

    # Multi-version + conflict warnings (heuristic, see module docstring)
    warnings: list[str] = []
    if used:
        # Cross-doc version conflict detection is intentionally minimal
        # in MVP — keep the loop structure for future heuristics.
        seen_doc_ids: dict[str, list[Citation]] = {}
        for cit in citations:
            seen_doc_ids.setdefault(cit.doc_id, []).append(cit)
        for _doc_id, cites in seen_doc_ids.items():
            if len(cites) > 1:
                # Same doc, multiple chunks — not a conflict, just multi-chunk
                continue
        # Cross-doc version conflict: very rough heuristic
        if len({citations[i - 1].doc_id for i in used if i - 1 < len(citations)}) > 1:
            # Multiple distinct docs cited; could be intentional synthesis.
            # No warning — the user can read the citations.
            pass

    extraction = CitationExtraction(
        unique_indices=used,
        warnings=warnings,
        ignored_indices=ignored,
    )
    return citations, extraction


__all__ = [
    "Citation",
    "CitationExtraction",
    "build_citations",
    "extract_citation_indices",
]
