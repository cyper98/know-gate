"""Answer generator: LLM call + citation enforcement + multi-version rule.

Inputs: the top-N reranked candidates + the user's question.
Outputs: the final answer text + a list of `Citation` objects the
UI can render.

The LLM is told to:
- Use only the provided sources
- Cite every claim with `[N]`
- Surface conflicts (e.g. "Source [1] says X, but [2] says Y")
- Answer in the user's language (we pass the language explicitly)
- Say "no information" when the sources are empty

We also enforce the multi-version rule (D2): if multiple candidates
point to the same doc and one is `active` / newer, we deprioritize
the `deprecated` / older one (drop it from the citation list, log a
warning). This keeps the user's answer current.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.llm.client import LLMClient
from app.llm.prompts import NO_ANSWER_PHRASES, build_answer_prompt
from app.logging import get_logger
from app.retrieval.citation_builder import Citation, build_citations
from app.retrieval.hybrid_search import SearchCandidate
from app.retrieval.reranker import RerankResult

logger = get_logger(__name__)


@dataclass(slots=True)
class GenerationResult:
    """Output of `AnswerGenerator.generate()`."""

    answer: str
    citations: list[Citation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    llm_model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    no_answer: bool = False  # True when the LLM said it can't find anything


class AnswerGenerator:
    """Build the prompt, call the LLM, post-process the response.

    Stateless — the LLMClient owns the connection. Create one per
    pipeline run, or reuse across runs.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        # If no client was passed, build one with a circuit breaker
        # wired to the configured primary / fallback models.
        if llm_client is not None:
            self._llm = llm_client
        else:
            from app.config import get_settings
            from app.llm.circuit_breaker import CircuitBreaker

            s = get_settings()
            breaker = CircuitBreaker(
                primary=s.litellm_default_model,
                fallback=s.litellm_fallback_model,
            )
            self._llm = LLMClient(breaker=breaker)

    async def generate(
        self,
        *,
        query: str,
        language: str,
        candidates: Sequence[SearchCandidate] | Sequence[RerankResult],
        doc_titles: dict[str, str] | None = None,
        doc_urls: dict[str, str] | None = None,
        doc_updated: dict | None = None,
        max_citations: int = 8,
    ) -> GenerationResult:
        """Run the LLM and return the structured answer.

        Args:
            query: the user's question (raw)
            language: ISO 639-1 code (`vi`, `en`, `zh`) — passed to
                the prompt so the LLM answers in the right language
            candidates: top-N reranked candidates
            doc_titles/doc_urls/doc_updated: optional maps for citation
                enrichment (filled in by the pipeline orchestrator)
            max_citations: cap on the number of citations attached to
                the response (frontend typically renders at most 8)

        Returns:
            `GenerationResult` with the answer text, citation list,
            warnings, and LLM usage metrics.
        """
        # Normalize input: RerankResult or SearchCandidate
        norm_candidates: list[SearchCandidate] = []
        for c in candidates:
            if isinstance(c, RerankResult):
                norm_candidates.append(c.candidate)
            else:
                norm_candidates.append(c)

        if not norm_candidates:
            # No candidates — short-circuit with the "no result" message
            return GenerationResult(
                answer="",
                no_answer=True,
                warnings=["no_candidates"],
            )

        # Build the prompt's chunks list (truncate to top-N)
        chunks_for_prompt = [
            {
                "citation_index": i + 1,
                "text": c.text or "",
                "section_title": c.section_title,
                "status": (c.payload or {}).get("status", "active"),
                "updated_at": (c.payload or {}).get("indexed_at"),
            }
            for i, c in enumerate(norm_candidates[:max_citations])
        ]

        messages = build_answer_prompt(
            chunks=chunks_for_prompt,
            question=query,
            language=language,
        )

        try:
            llm_result = await self._llm.complete(messages)
        except Exception as e:
            logger.exception("answer_llm_failed", error=str(e))
            # Surface the failure to the pipeline (it decides whether
            # to retry with fallback or return a 5xx)
            raise

        # Post-process: build citations, detect "no answer" phrase
        answer_text = llm_result.text.strip()
        citations, extraction = build_citations(
            norm_candidates[:max_citations],
            answer_text,
            doc_titles=doc_titles,
            doc_urls=doc_urls,
            doc_updated=doc_updated,
        )

        no_answer = any(p in answer_text.lower() for p in NO_ANSWER_PHRASES)
        warnings = list(extraction.warnings)
        if extraction.ignored_indices:
            warnings.append(
                f"llm_used_invalid_citation_numbers:{extraction.ignored_indices}"
            )

        return GenerationResult(
            answer=answer_text,
            citations=citations,
            warnings=warnings,
            llm_model=llm_result.model,
            prompt_tokens=llm_result.prompt_tokens,
            completion_tokens=llm_result.completion_tokens,
            cost_usd=llm_result.cost_usd,
            latency_ms=llm_result.latency_ms,
            no_answer=no_answer,
        )


__all__ = ["AnswerGenerator", "GenerationResult"]
