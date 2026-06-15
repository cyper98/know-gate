"""Query sub-command (``kg query "..."``).

Calls ``POST /api/v1/query`` and renders the answer + numbered citations.

Default (human) output: a panel with the LLM answer and a table of
citations. JSON output (``--json``): full response body.

Accepts the question from:
- Positional arg (``kg query "What is RAG?"``)
- ``--file path.txt`` (read the file as the question — useful for
  multi-line prompts or pasting from a doc)
- ``--stdin`` (read from stdin; mutually exclusive with positional)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .client import KnowGateClient
from .output import Output


def _read_question(
    question: str | None,
    file: Path | None,
    use_stdin: bool,
) -> str:
    """Resolve the question text from the three possible sources.

    Exactly one source must be provided. Empty questions are rejected
    so the user gets a clear error rather than a silent 400 from the API.
    """
    sources = sum(bool(x) for x in (question, file, use_stdin))
    if sources == 0:
        raise ValueError("Provide a question as an argument, --file <path>, or --stdin.")
    if sources > 1:
        raise ValueError("Use only one of: positional question, --file, or --stdin.")
    if use_stdin:
        text = sys.stdin.read()
    elif file is not None:
        if not file.exists():
            raise FileNotFoundError(f"Question file not found: {file}")
        text = file.read_text(encoding="utf-8")
    else:
        text = question or ""
    text = text.strip()
    if not text:
        raise ValueError("Question is empty.")
    return text


def run(
    client: KnowGateClient,
    out: Output,
    *,
    question: str | None = None,
    file: Path | None = None,
    use_stdin: bool = False,
    language: str | None = None,
    bypass_cache: bool = False,
    show_citations: bool = True,
) -> dict[str, Any]:
    """Submit a question and render the result.

    Returns the raw API response (so JSON-mode callers can introspect)
    and prints the human-friendly representation unless ``--json``.
    """
    try:
        q = _read_question(question, file, use_stdin)
    except (ValueError, FileNotFoundError) as exc:
        out.error(str(exc))
        raise

    payload: dict[str, Any] = {"question": q}
    if language:
        payload["language"] = language
    if bypass_cache:
        payload["bypass_cache"] = True

    with out.spinner("Thinking…"):
        body = client.post("/query", json=payload)

    if out.json_mode:
        out.json(body)
        return body

    # Human mode
    answer = body.get("answer") or ""
    no_result = body.get("no_result")
    if no_result:
        out.warning(f"No answer: {no_result.get('message', '')}")
        if no_result.get("suggestions"):
            for s in no_result["suggestions"]:
                out.info(f"  • {s}")
    elif answer:
        out.panel(answer, title="Answer")
    else:
        out.warning("The API returned an empty answer.")

    citations = body.get("citations") or []
    if show_citations and citations:
        rows: list[dict[str, Any]] = []
        for c in citations:
            rows.append(
                {
                    "n": c.get("index", "?"),
                    "title": c.get("title", ""),
                    "section": c.get("section_title") or "",
                    "page": c.get("page_number") if c.get("page_number") is not None else "",
                    "source": c.get("source") or "",
                    "score": f"{float(c.get('score', 0)):.2f}",
                }
            )
        out.table(
            rows,
            columns=[
                ("n", "#"),
                ("title", "Title"),
                ("section", "Section"),
                ("page", "Page"),
                ("source", "Source"),
                ("score", "Score"),
            ],
        )

    warnings = body.get("warnings") or []
    for w in warnings:
        out.warning(w)

    # Footer with metadata
    footer_bits: list[str] = []
    if body.get("llm_model"):
        footer_bits.append(f"model={body['llm_model']}")
    if body.get("cache_hit"):
        footer_bits.append("cache=hit")
    if body.get("latency_ms") is not None:
        footer_bits.append(f"{body['latency_ms']}ms")
    if body.get("cost_usd") is not None:
        footer_bits.append(f"${body['cost_usd']:.4f}")
    if footer_bits:
        out.info(" · ".join(footer_bits))

    return body


__all__ = ["run"]
