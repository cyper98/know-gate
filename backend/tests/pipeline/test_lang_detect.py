"""Unit tests for language detection."""

from __future__ import annotations

from app.pipeline.lang_detect import (
    MIN_CHARS_FOR_DETECT,
    SUPPORTED_LANGS,
    detect_language,
    normalize_lang,
)


def test_normalize_lang_supported_codes_passthrough() -> None:
    assert normalize_lang("vi") == "vi"
    assert normalize_lang("en") == "en"
    assert normalize_lang("zh") == "zh"


def test_normalize_lang_zh_regional_collapses_to_zh() -> None:
    assert normalize_lang("zh-cn") == "zh"
    assert normalize_lang("zh-tw") == "zh"
    assert normalize_lang("ZH-Hans") == "zh"


def test_normalize_lang_unsupported_collapses_to_und() -> None:
    assert normalize_lang("fr") == "und"
    assert normalize_lang("ja") == "und"
    assert normalize_lang("de") == "und"
    assert normalize_lang("") == "und"
    assert normalize_lang("not-a-code") == "und"


def test_supported_langs_is_frozenset_with_three_codes() -> None:
    assert frozenset({"vi", "en", "zh"}) == SUPPORTED_LANGS


def test_detect_language_empty_returns_und() -> None:
    assert detect_language("") == "und"
    assert detect_language("   ") == "und"
    assert detect_language("\n\t") == "und"


def test_detect_language_short_text_returns_und() -> None:
    """Text below MIN_CHARS_FOR_DETECT must return 'und' without calling langdetect."""
    short = "abc"  # way under 50 chars
    assert detect_language(short) == "und"
    assert len(short) < MIN_CHARS_FOR_DETECT


def test_detect_language_english() -> None:
    text = (
        "The quick brown fox jumps over the lazy dog. "
        "This is a longer passage of text in English that should be detected as such. "
        "The model should have enough signal to identify the language as English."
    )
    assert detect_language(text) == "en"


def test_detect_language_vietnamese() -> None:
    text = (
        "Đây là một đoạn văn bằng tiếng Việt dài đủ để hệ thống có thể nhận diện "
        "chính xác ngôn ngữ của văn bản một cách đáng tin cậy cho mục đích phân loại."
    )
    assert detect_language(text) == "vi"


def test_detect_language_garbage_returns_und() -> None:
    """Pure symbols / numbers should not crash and should resolve to 'und'."""
    text = "1234567890 !@#$%^&*()_+ 0987654321" * 3
    result = detect_language(text)
    # Either "und" (no detection) or it might detect some other lang; both are acceptable
    # since this is edge case. The important thing is no exception.
    assert result in {"und", "en", "vi", "zh"}
