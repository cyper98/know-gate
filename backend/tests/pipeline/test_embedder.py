"""Unit tests for the embedder.

We never load the real bge-m3 model in tests (~2.3GB). We patch
`SentenceTransformer` to a fake that returns deterministic random
vectors, then assert the wrapper's batch / normalize / dim behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.pipeline import embedder


class _FakeModel:
    """A drop-in fake for `SentenceTransformer`.

    Honors the `normalize_embeddings=True` kwarg the way the real
    library does — L2-normalize each row. Without this, the unit-norm
    test would fail (the fake would return random unit-variance noise).
    Also sets `embedder._model_name` so `model_version()` derives the
    right slug (the real `_get_model` would do this as a side effect).
    """

    def __init__(self, name: str, device: str = "cpu") -> None:
        self.name = name
        self.device = device
        self._dim = embedder.DEFAULT_DIM
        self.cache_folder = "/tmp/fake-hf-cache"
        # Mirror what the real _get_model() would set, so model_version()
        # returns the slug matching this fake's name.
        embedder._model_name = name  # type: ignore[attr-defined]

    def encode(self, texts, **kwargs):
        n = len(texts)
        rng = np.random.default_rng(seed=hash(tuple(texts)) % (2**32))
        vecs = rng.standard_normal((n, self._dim)).astype(np.float32)
        if kwargs.get("normalize_embeddings"):
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            vecs = vecs / norms
        return vecs

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset the cached model before each test so the import path runs."""
    embedder.reset_for_tests()
    yield
    embedder.reset_for_tests()


def test_embed_batch_returns_correct_shape() -> None:
    with patch.object(embedder, "_get_model", return_value=_FakeModel("BAAI/bge-m3")):
        vecs = embedder.embed_batch(["a", "b", "c", "d"])
    assert vecs.shape == (4, embedder.DEFAULT_DIM)
    assert vecs.dtype == np.float32


def test_embed_batch_empty_returns_empty_array() -> None:
    with patch.object(embedder, "_get_model", return_value=_FakeModel("BAAI/bge-m3")):
        vecs = embedder.embed_batch([])
    assert vecs.shape == (0, embedder.DEFAULT_DIM)
    assert vecs.dtype == np.float32


def test_embed_batch_normalizes_vectors_to_unit_length() -> None:
    """The wrapper requests normalize_embeddings=True, so vectors must be unit-length."""
    with patch.object(embedder, "_get_model", return_value=_FakeModel("BAAI/bge-m3")):
        vecs = embedder.embed_batch(["alpha", "beta"])
    norms = np.linalg.norm(vecs, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-5)


def test_embed_query_returns_list_of_float() -> None:
    with patch.object(embedder, "_get_model", return_value=_FakeModel("BAAI/bge-m3")):
        vec = embedder.embed_query("search this")
    assert isinstance(vec, list)
    assert len(vec) == embedder.DEFAULT_DIM
    assert all(isinstance(x, float) for x in vec)


def test_embed_dim_returns_1024_for_bge_m3() -> None:
    with patch.object(embedder, "_get_model", return_value=_FakeModel("BAAI/bge-m3")):
        assert embedder.embed_dim() == 1024


def test_model_version_uses_bge_m3_slug() -> None:
    """The version string is stored in chunks.embedding_model — must be stable."""
    with patch.object(embedder, "_get_model", return_value=_FakeModel("BAAI/bge-m3")):
        v = embedder.model_version()
    assert v == "bge-m3-v1.0.0"


def test_model_version_different_model_different_slug() -> None:
    with patch.object(embedder, "_get_model", return_value=_FakeModel("intfloat/e5-large-v2")):
        v = embedder.model_version()
    assert v.startswith("e5-large-v2-")


def test_prewarm_calls_get_model() -> None:
    """`prewarm_embedder` is the worker startup hook — must trigger a load."""
    with patch.object(embedder, "_get_model", return_value=_FakeModel("BAAI/bge-m3")) as mock_get:
        embedder.prewarm_embedder()
    mock_get.assert_called_once()


def test_aembed_batch_runs_in_thread() -> None:
    """`aembed_batch` is the async entrypoint — should not block the loop."""
    import asyncio

    async def _run() -> np.ndarray:
        with patch.object(embedder, "_get_model", return_value=_FakeModel("BAAI/bge-m3")):
            return await embedder.aembed_batch(["x", "y"])

    vecs = asyncio.run(_run())
    assert vecs.shape == (2, embedder.DEFAULT_DIM)


def test_embed_batch_uses_configured_batch_size() -> None:
    """The wrapper reads `embedding_batch_size` from settings."""
    fake = MagicMock()
    fake.encode = MagicMock(return_value=np.zeros((1, 1024), dtype=np.float32))
    fake.get_sentence_embedding_dimension = MagicMock(return_value=1024)
    with patch.object(embedder, "_get_model", return_value=fake), \
         patch("app.pipeline.embedder._resolve_batch_size", return_value=16):
        embedder.embed_batch(["text"])
    fake.encode.assert_called_once()
    # The batch_size kwarg should be 16
    kwargs = fake.encode.call_args.kwargs
    assert kwargs.get("batch_size") == 16
