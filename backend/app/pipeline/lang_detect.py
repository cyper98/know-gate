"""Language detection (langdetect) with a vi/en/zh whitelist.

The architecture calls for ISO 639-1 codes. We only ever emit vi / en /
zh / und (undetermined). `langdetect` returns a wider alphabet (it
supports 50+ languages) — we collapse everything else to 'und' so the
Qdrant payload index stays small and the UI can render a 3-language UI.

Detection is per-chunk (not per-doc) so a mixed-language document gets
honest per-chunk language tags. Short text (< 50 chars) is skipped
because langdetect is unreliable on small inputs.
"""

from __future__ import annotations

import logging

from langdetect import DetectorFactory, detect_langs

logger = logging.getLogger(__name__)

# Make detection deterministic (langdetect uses a non-seeded random by
# default, which makes our Qdrant payloads non-reproducible).
DetectorFactory.seed = 0

# Whitelisted languages (per architecture §4 data model).
SUPPORTED_LANGS = frozenset({"vi", "en", "zh"})

# Below this character count, detection is too noisy. We treat short
# fragments as undetermined rather than risk a wrong tag.
MIN_CHARS_FOR_DETECT = 50


def normalize_lang(raw: str) -> str:
    """Map a raw langdetect output to our 4-value alphabet (vi/en/zh/und).

    `zh-cn` / `zh-tw` collapse to `zh`. Anything else is `und`.
    """
    if not raw:
        return "und"
    code = raw.lower().split("-", 1)[0]
    if code in SUPPORTED_LANGS:
        return code
    return "und"


def detect_language(text: str) -> str:
    """Return one of 'vi' / 'en' / 'zh' / 'und' for the given text.

    Falls back to 'und' on:
    - empty / whitespace-only input
    - text shorter than MIN_CHARS_FOR_DETECT
    - langdetect raising (corpus mismatch, decoder error, etc.)
    - best-guess probability below threshold
    """
    if not text or not text.strip() or len(text.strip()) < MIN_CHARS_FOR_DETECT:
        return "und"

    try:
        # detect_langs returns a list of Lang objects sorted by probability.
        # We pick the top one if it crosses the threshold, else 'und'.
        candidates = detect_langs(text)
    except Exception as e:  # langdetect raises on garbage / no-features input
        logger.debug("lang_detect_failed", error=str(e))
        return "und"

    if not candidates:
        return "und"

    top = candidates[0]
    if top.prob < 0.5:
        # Top candidate is weak — treat as undetermined so the UI can show
        # an "auto / unknown" label.
        return "und"

    return normalize_lang(top.lang)


__all__ = ["MIN_CHARS_FOR_DETECT", "SUPPORTED_LANGS", "detect_language", "normalize_lang"]
