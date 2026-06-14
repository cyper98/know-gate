"""Document chunker (heading-aware + recursive char fallback).

Strategy:
1. For each `Section` from the parser, join its text and try to keep
   the whole section as one chunk.
2. If a section exceeds `max_tokens` (default 1024), split it with a
   recursive character splitter (paragraph -> sentence -> word) so we
   break on natural boundaries first.
3. Adjacent chunks get a 10% overlap (clipped to `overlap_tokens`) so
   the embedding model sees the boundary context — this is what makes
   cross-paragraph questions retrievable.

Output `Chunk` records carry:
- `text` — the chunk body
- `section_title` — copied from the source section
- `chunk_index` — global 0-based index across the whole document
- `page_number` — copied from the source section (None when unknown)
- `token_count` — exact tiktoken count
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from app.pipeline.parser import ParsedDoc
from app.pipeline.tokenizer import count_tokens

logger = logging.getLogger(__name__)

# Default sizes from architecture (chunk = 512 tokens target, 1024 max).
DEFAULT_TARGET_TOKENS = 512
DEFAULT_MAX_TOKENS = 1024
DEFAULT_OVERLAP_RATIO = 0.10  # 10% of target

# Recursive character splitter boundaries (in priority order).
# We try to break on the most meaningful separator first; the last entry
# is the fallback that always works (character-by-character).
_RECURSIVE_SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "。", " ", ""]


@dataclass(slots=True)
class Chunk:
    """One output chunk — ready for embedding + Qdrant write."""

    text: str
    section_title: str
    chunk_index: int
    token_count: int
    page_number: int | None = None


# === Public API ===

def chunk_by_sections(
    parsed: ParsedDoc,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[Chunk]:
    """Chunk a ParsedDoc into `Chunk` records.

    Args:
        parsed: output of the parser
        target_tokens: soft target — try to keep chunks around this size
        max_tokens: hard cap — chunks must not exceed this (split if needed)
        overlap_ratio: 0.0..1.0, fraction of target that overlaps between
            adjacent chunks (used only when a section is split)

    Returns:
        List of `Chunk` records with monotonic `chunk_index` from 0.
    """
    if target_tokens <= 0:
        raise ValueError(f"target_tokens must be > 0, got {target_tokens}")
    if max_tokens < target_tokens:
        raise ValueError(
            f"max_tokens ({max_tokens}) must be >= target_tokens ({target_tokens})"
        )
    if not 0.0 <= overlap_ratio < 1.0:
        raise ValueError(f"overlap_ratio must be in [0.0, 1.0), got {overlap_ratio}")

    overlap_tokens = int(target_tokens * overlap_ratio)
    chunks: list[Chunk] = []
    next_index = 0

    for section in parsed.sections:
        text = section.text.strip()
        if not text:
            continue

        n_tokens = count_tokens(text)
        if n_tokens <= max_tokens:
            # Section fits in one chunk
            chunks.append(
                Chunk(
                    text=text,
                    section_title=section.title,
                    chunk_index=next_index,
                    token_count=n_tokens,
                    page_number=section.page_number,
                )
            )
            next_index += 1
            continue

        # Section too big — split with overlap
        pieces = _recursive_split(text, max_tokens)
        logger.debug(
            "chunk_split_section",
            section_title=section.title,
            original_tokens=n_tokens,
            pieces=len(pieces),
        )

        prev_tail: str | None = None
        for piece in pieces:
            if prev_tail and overlap_tokens > 0:
                combined = prev_tail + piece
                # Trim overlap tail if it would push us over max_tokens
                combined = _trim_to_tokens(combined, max_tokens)
                piece = combined

            piece = piece.strip()
            if not piece:
                continue

            chunks.append(
                Chunk(
                    text=piece,
                    section_title=section.title,
                    chunk_index=next_index,
                    token_count=count_tokens(piece),
                    page_number=section.page_number,
                )
            )
            next_index += 1

            # Build the overlap tail for the NEXT piece (last ~overlap_tokens worth)
            prev_tail = _tail_for_overlap(piece, overlap_tokens)

    return chunks


# === Internals ===

def _recursive_split(text: str, max_tokens: int) -> list[str]:
    """Recursively split `text` so each piece is <= max_tokens.

    Tries the separators in order; for each separator we split the text
    on it, then recurse on any piece that's still too big. The empty
    string separator is the recursion base (split into chars).
    """
    return list(_split_recursive(text, max_tokens, 0))


def _split_recursive(text: str, max_tokens: int, depth: int) -> Iterable[str]:
    if count_tokens(text) <= max_tokens:
        if text:
            yield text
        return

    if depth >= len(_RECURSIVE_SEPARATORS):
        # Last resort: char-split (should never hit if max_tokens is sane)
        for i in range(0, len(text), max_tokens):
            yield text[i : i + max_tokens]
        return

    sep = _RECURSIVE_SEPARATORS[depth]
    if sep == "":
        for i in range(0, len(text), max_tokens):
            yield text[i : i + max_tokens]
        return

    pieces = text.split(sep)
    # If splitting on this separator didn't help (single piece), go deeper
    if len(pieces) == 1:
        yield from _split_recursive(text, max_tokens, depth + 1)
        return

    # Reassemble pieces with the separator re-attached (except last)
    buffer = ""
    for piece in pieces:
        candidate = buffer + (sep if buffer else "") + piece
        if count_tokens(candidate) <= max_tokens:
            buffer = candidate
            continue
        # Flush buffer
        if buffer:
            yield from _split_recursive(buffer, max_tokens, depth + 1)
        buffer = piece
    if buffer:
        yield from _split_recursive(buffer, max_tokens, depth + 1)


def _tail_for_overlap(text: str, overlap_tokens: int) -> str:
    """Return the last ~`overlap_tokens` of `text` (for cross-chunk overlap)."""
    if overlap_tokens <= 0 or not text:
        return ""
    # Walk tokens from the end, collect until we hit the budget
    enc = None
    try:
        # Use the cached encoder from tokenizer; lazy import to avoid cycle
        from app.pipeline.tokenizer import get_encoder
        enc = get_encoder()
    except Exception:  # pragma: no cover
        return text[-200:]

    tokens = enc.encode(text, disallowed_special=())
    if len(tokens) <= overlap_tokens:
        return text
    tail_tokens = tokens[-overlap_tokens:]
    return enc.decode(tail_tokens)


def _trim_to_tokens(text: str, max_tokens: int) -> str:
    """Trim `text` to <= max_tokens (cuts from the front to preserve the end)."""
    if count_tokens(text) <= max_tokens:
        return text
    try:
        from app.pipeline.tokenizer import get_encoder
        enc = get_encoder()
    except Exception:  # pragma: no cover
        return text[-max_tokens * 4 :]  # ~4 chars/token fallback

    tokens = enc.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return text
    return enc.decode(tokens[-max_tokens:])


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_OVERLAP_RATIO",
    "DEFAULT_TARGET_TOKENS",
    "Chunk",
    "chunk_by_sections",
]
