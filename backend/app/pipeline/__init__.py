"""Ingestion pipeline package (parse + chunk + embed + index).

The pipeline is the workhorse that turns raw documents into searchable
chunks in Qdrant. It is invoked from the Celery worker (see
`app.tasks.ingest`) and runs entirely on the worker side (heavy ML +
network I/O). The API process does not import from this package.

Order of operations in a single document run:

    download from MinIO  ->  parse_doc  ->  chunk_by_sections
        ->  embed_batch  ->  upsert_chunks_bulk  ->  write Chunk rows
        ->  update Document.status

All steps are idempotent: re-running on the same document produces the
same Qdrant point IDs (deterministic UUID v5 from doc_id + chunk_index).
"""

from app.pipeline.lang_detect import detect_language, normalize_lang
from app.pipeline.tokenizer import count_tokens, get_encoder

__all__ = [
    "count_tokens",
    "detect_language",
    "get_encoder",
    "normalize_lang",
]
