"""Tokenizer helper (tiktoken cl100k_base).

Single source of truth for token counts used by the chunker and by
Qdrant payload metadata. The encoder is cached module-wide to avoid the
~50ms cold-start cost on every call.

We use cl100k_base (the GPT-4 / text-embedding-3 tokenizer) because
bge-m3 is not tokenizer-aligned with tiktoken, but token budgets are
approximate anyway. cl100k_base is a reasonable proxy for the
~512-token chunks the architecture calls for.
"""

from __future__ import annotations

from functools import lru_cache

import tiktoken

# cl100k_base is the GPT-4 / text-embedding-3 family encoder. It is a
# reasonable approximation for bge-m3 chunk sizing — the actual bge-m3
# tokenizer is not public, so we use a stable open tokenizer for budgets.
_ENCODER_NAME = "cl100k_base"


@lru_cache(maxsize=1)
def get_encoder() -> tiktoken.Encoding:
    """Return a cached tiktoken encoder (singleton)."""
    return tiktoken.get_encoding(_ENCODER_NAME)


def count_tokens(text: str) -> int:
    """Count tokens in `text` using the cached encoder.

    Empty / whitespace-only text returns 0 (defensive — never negative).
    Whitespace-only counts as 0 because tiktoken encodes whitespace as
    tokens, but a chunk that's just whitespace is not useful.
    """
    if not text or not text.strip():
        return 0
    return len(get_encoder().encode(text, disallowed_special=()))


__all__ = ["count_tokens", "get_encoder"]
