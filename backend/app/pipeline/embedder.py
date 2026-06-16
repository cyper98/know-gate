"""bge-m3 embedder wrapper (sentence-transformers).

Loads the BAAI/bge-m3 model lazily on first use, embeds batches of
text, and normalizes vectors to unit length so cosine = dot product
(the Qdrant collection is configured with COSINE distance).

The model is process-local. The worker pre-warms it at startup via
`prewarm_embedder()` (called from the Celery worker's startup hook) to
avoid a 5s+ cold start on the first request after boot.

Design notes:
- `embed_batch` is sync (sentence-transformers is CPU-bound and
  releases the GIL under torch). The pipeline orchestrator runs it
  via `asyncio.to_thread` to keep the event loop responsive.
- `embed_query` is a single-text convenience for the read path
  (deferred to the retrieval work block; included here for symmetry).
- Vectors are L2-normalized so the Qdrant COSINE distance is exact
  (no extra normalization at search time).
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import numpy as np

from app.logging import get_logger

logger = get_logger(__name__)

# Default model name + dim (mirrors app.config.Settings defaults).
DEFAULT_MODEL_NAME = "BAAI/bge-m3"
DEFAULT_DIM = 1024

# Thread-safe lazy init — Celery workers are threaded (prefork model),
# so we must guard the model load with a lock.
_lock = threading.Lock()
_model = None  # type: ignore[var-annotated]
_model_name: str | None = None


def _get_model(model_name: str = DEFAULT_MODEL_NAME):
    """Return the loaded model (loading on first call, thread-safe)."""
    global _model, _model_name
    if _model is not None and _model_name == model_name:
        return _model

    with _lock:
        if _model is not None and _model_name == model_name:
            return _model  # double-check after lock

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        except ImportError as e:  # pragma: no cover - import-time guard
            raise RuntimeError(
                "sentence-transformers is not installed; pip install 'sentence-transformers>=3.2.0'"
            ) from e

        logger.info("embedder_loading", model=model_name)
        device = _resolve_device()
        model = SentenceTransformer(model_name, device=device)
        # Warm up so the first real call doesn't pay the JIT cost
        model.encode(["warmup"], normalize_embeddings=True)

        _model = model
        _model_name = model_name
        logger.info(
            "embedder_loaded",
            model=model_name,
            dim=model.get_sentence_embedding_dimension(),
            device=str(device),
        )
        return _model


def _resolve_device() -> str:
    """Pick CPU / CUDA based on env (no CUDA at MVP — CPU only)."""
    try:
        from app.config import get_settings
        return get_settings().embedding_device
    except Exception:  # pragma: no cover - tests without settings
        return "cpu"


def _slugify_model(name: str) -> str:
    """BAAI/bge-m3 -> bge-m3 (used in chunks.embedding_model)."""
    return name.split("/", 1)[-1].lower().replace("_", "-")


# === Public API ===

def model_version() -> str:
    """Return the loaded model's version string (e.g., 'bge-m3-v1.0.0').

    The version is derived from the model name. bge-m3 has no public
    version tag, so we encode the model name + a fixed revision. A real
    release would use git SHA or HuggingFace revision id.
    """
    loaded = _model_name
    if loaded is None:
        _get_model()
        loaded = _model_name or DEFAULT_MODEL_NAME
    return f"{_slugify_model(loaded)}-v1.0.0"


def embed_dim() -> int:
    """Return the embedding dimension (1024 for bge-m3)."""
    try:
        return _get_model().get_sentence_embedding_dimension()
    except Exception:
        return DEFAULT_DIM


def embed_batch(
    texts: list[str],
    *,
    batch_size: int | None = None,
    normalize: bool = True,
) -> np.ndarray:
    """Embed a batch of texts. Returns np.ndarray of shape (N, dim), float32.

    Vectors are L2-normalized by default. Empty input returns an empty
    array with the right dim (callers can short-circuit before calling).
    """
    if not texts:
        # Caller responsibility to check, but be defensive
        return np.zeros((0, embed_dim()), dtype=np.float32)

    model = _get_model()
    bs = batch_size or _resolve_batch_size()
    logger.debug("embed_batch", n=len(texts), batch_size=bs)

    vectors = model.encode(
        texts,
        batch_size=bs,
        normalize_embeddings=normalize,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    # Force float32 (Qdrant is f32). Some configs come back as f64.
    return vectors.astype(np.float32, copy=False)


async def aembed_batch(texts: list[str], **kwargs) -> np.ndarray:
    """Async wrapper around `embed_batch` (runs the sync call in a thread)."""
    return await asyncio.to_thread(embed_batch, texts, **kwargs)


def embed_query(text: str) -> list[float]:
    """Embed a single query (convenience for the read path).

    Returns a plain Python list[float] so it can go straight to a
    Qdrant `query_points` call without numpy in the way.
    """
    vec = embed_batch([text])
    if vec.size == 0:
        return [0.0] * embed_dim()
    return vec[0].tolist()


def prewarm_embedder(model_name: str = DEFAULT_MODEL_NAME) -> None:
    """Load the model at worker startup. Safe to call multiple times."""
    logger.info("embedder_prewarm_start", model=model_name)
    _get_model(model_name)
    logger.info("embedder_prewarm_done", model=model_name)


def _resolve_batch_size() -> int:
    try:
        from app.config import get_settings
        s = get_settings()
        return s.embedding_batch_size
    except Exception:  # pragma: no cover
        return 8  # default to CPU-safe value


def reset_for_tests() -> None:
    """Drop the cached model. For tests only — never call in production."""
    global _model, _model_name
    with _lock:
        _model = None
        _model_name = None


if TYPE_CHECKING:  # pragma: no cover
    pass


__all__ = [
    "DEFAULT_DIM",
    "DEFAULT_MODEL_NAME",
    "aembed_batch",
    "embed_batch",
    "embed_dim",
    "embed_query",
    "model_version",
    "prewarm_embedder",
    "reset_for_tests",
]
