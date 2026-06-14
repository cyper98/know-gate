#!/usr/bin/env python
"""Download the bge-m3 embedding model to the local HuggingFace cache.

Run this from the backend container (or host) BEFORE booting the worker
in offline / air-gapped environments. After this script completes, the
worker can start without network access to huggingface.co.

    python -m scripts.load_bge_model

By default the model is BAAI/bge-m3 (1024-dim, ~2.3GB on disk).
Override with --model-name if you swap in a different embedder.
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-download the embedding model")
    parser.add_argument(
        "--model-name",
        default="BAAI/bge-m3",
        help="HuggingFace model id (default: BAAI/bge-m3)",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Override HF_HOME / model cache directory",
    )
    args = parser.parse_args()

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print(
            "ERROR: sentence-transformers is not installed.\n"
            "       pip install 'sentence-transformers>=3.2.0'",
            file=sys.stderr,
        )
        return 1

    print(f"Downloading model: {args.model_name}")
    print("This may take a few minutes (~2.3GB for bge-m3)...")

    kwargs = {}
    if args.cache_dir:
        kwargs["cache_folder"] = args.cache_dir

    try:
        model = SentenceTransformer(args.model_name, **kwargs)
    except Exception as e:
        print(f"ERROR: failed to download: {e}", file=sys.stderr)
        return 2

    dim = model.get_sentence_embedding_dimension()
    print(f"OK: model loaded, embedding_dim={dim}")
    print(f"Model cache: {model.cache_folder if hasattr(model, 'cache_folder') else '(default HF cache)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
