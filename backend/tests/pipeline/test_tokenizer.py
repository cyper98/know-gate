"""Unit tests for the tokenizer (tiktoken wrapper)."""

from __future__ import annotations

from app.pipeline.tokenizer import count_tokens, get_encoder


def test_count_tokens_empty_returns_zero() -> None:
    assert count_tokens("") == 0


def test_count_tokens_whitespace_only_returns_zero() -> None:
    assert count_tokens("   \n\t  ") == 0


def test_count_tokens_simple_english() -> None:
    # "hello world" -> 2 tokens in cl100k_base
    n = count_tokens("hello world")
    assert n == 2


def test_count_tokens_repeated_text_grows() -> None:
    """Long text returns strictly more tokens than short text."""
    short = count_tokens("hello world")
    long = count_tokens("hello world " * 100)
    assert long > short
    # The long text should have at least 100x the tokens of a single repetition
    assert long >= short * 50  # conservative lower bound (BPE may compress repeats)


def test_get_encoder_returns_cached_singleton() -> None:
    e1 = get_encoder()
    e2 = get_encoder()
    assert e1 is e2  # lru_cache hit


def test_count_tokens_unicode_handled() -> None:
    # Vietnamese diacritics
    n = count_tokens("Xin chào thế giới")
    assert n > 0
    # Should not raise
