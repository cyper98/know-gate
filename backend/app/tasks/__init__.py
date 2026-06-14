"""Celery tasks. The API process declares them; workers + beat run them.

Each task should be:
- Idempotent (safe to re-run on retry)
- Self-contained (creates its own DB session + DB transaction)
- Fire-and-forget friendly (don't block the request thread)
"""
