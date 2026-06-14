"""System prompt + answer-formatting rules for the LLM.

The prompt is versioned (`KG_PROMPT_VERSION`) so we can A/B test
prompt revisions against the eval set. The version is stored in the
`Query.llm_model` column alongside the model name as a sanity check
on the cache key (a cache hit on a stale prompt is worse than a miss).

Design decisions (per brainstorm §17):
- Answer ONLY using the provided sources. No external knowledge.
- Always cite with numbered footnotes `[1]`, `[2]`, ... in the body.
- If sources conflict, surface the conflict ("[1] says X, but [2] says Y")
  and recommend the newer / more-official source.
- Answer in the SAME language as the user's question (per D4 — no
  translation, even if the source is in a different language).
- If the sources do not contain the answer, say so explicitly and
  do NOT guess. The frontend can offer "no result" UX from this signal.
- Citations are returned as `[N]` tokens in the body, then mapped to
  full citation objects by `citation_builder.py`.
"""

from __future__ import annotations

# Bump this whenever the prompt changes meaningfully. Used as a cache
# prefix so semantic-cache entries from a previous prompt never bleed
# into the new one.
KG_PROMPT_VERSION = "1.0.0"


# System prompt (in English — the LLM understands any of vi/en/zh).
# Kept compact: the LLM is good at following short, dense instructions.
SYSTEM_PROMPT = """You are KnowGate, a permission-aware RAG assistant for an internal knowledge base.

RULES (follow strictly):

1. Answer ONLY using the provided sources below. Do NOT use outside knowledge.
2. If the sources do not contain the answer, reply exactly:
   "I could not find relevant information in the available sources."
   (in the user's language)
3. Every factual claim MUST cite a source with a numbered footnote:
   [1], [2], [3], ... matching the order sources are listed below.
4. If two sources disagree, mention the conflict explicitly and prefer
   the one marked "newer" or with status "active" (vs. "deprecated").
5. Answer in the SAME language as the user's question. Never translate
   the answer.
6. Be concise. Use bullet points for multi-part answers. No preamble,
   no "I am an AI assistant" disclaimers.
7. Do not invent citation numbers. If you use 3 sources, the max
   footnote is [3].
"""


# User prompt template. `chunks` is the joined text of the top-N ranked
# chunks (with their citation number in the body). `question` is the
# user's raw input.
USER_PROMPT_TEMPLATE = """LANGUAGE: {language}

SOURCES (cite these by number):

{chunks_block}

USER QUESTION:
{question}

Your answer (with numbered citations):"""


def build_answer_prompt(
    *,
    chunks: list[dict],
    question: str,
    language: str,
) -> list[dict]:
    """Build the OpenAI-style messages list for the LLM.

    Each chunk in `chunks` must have a `citation_index` (1-based) and
    a `text` field. The prompt renders the chunks as a numbered list
    so the model can reference them by `[N]`.

    Args:
        chunks: ordered list of dicts with keys `citation_index`, `text`,
            plus optional `section_title`, `updated_at`, `status` for
            the LLM to know which is newer / authoritative.
        question: the raw user question (already preprocessed).
        language: ISO 639-1 code (`vi`, `en`, `zh`).

    Returns:
        List of `{"role": "system"|"user", "content": "..."}` dicts
        suitable for OpenAI-style chat completion APIs.
    """
    chunks_lines = []
    for c in chunks:
        idx = c["citation_index"]
        title = c.get("section_title") or "(no title)"
        status = c.get("status") or "active"
        updated = c.get("updated_at") or "unknown"
        text = c.get("text", "").strip()
        chunks_lines.append(
            f"[{idx}] (section={title!r}, status={status}, updated={updated})\n{text}"
        )
    chunks_block = "\n\n---\n\n".join(chunks_lines) if chunks_lines else "(no sources)"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
            language=language,
            chunks_block=chunks_block,
            question=question.strip(),
        )},
    ]


# Regex used by `citation_builder` to extract [N] tokens from the LLM
# response. Captures the citation number so we can map it back to a
# chunk / source.
_CITATION_RE = r"\[(\d+)\]"


# Phrase the LLM uses to signal "no answer in sources". The frontend
# can short-circuit and offer related-doc suggestions.
NO_ANSWER_PHRASES = (
    "could not find relevant information",
    "không tìm thấy thông tin",
    "未找到相关信息",
)


__all__ = [
    "KG_PROMPT_VERSION",
    "NO_ANSWER_PHRASES",
    "SYSTEM_PROMPT",
    "USER_PROMPT_TEMPLATE",
    "build_answer_prompt",
]
