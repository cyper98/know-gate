"""Celery application factory (broker = Redis, sync workers).

The API process imports this to declare the Celery app; the worker + beat
processes run it as their entrypoint (`celery -A app.celery_app worker`).

All tasks must be idempotent — workers may be killed mid-execution and the
job will be retried. Sync tasks are especially sensitive: a partial sync
that crashed must be safe to re-run.
"""

from __future__ import annotations

import logging

from celery import Celery

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _make_celery() -> Celery:
    """Build the Celery app with project-standard config."""
    # If broker URL is not explicitly set, derive it from the Redis URL.
    # Celery uses DB 0 for the broker and DB 1 for the result backend by
    # convention (matches the pattern used in deploy/docker-compose.yml).
    broker = settings.celery_broker_url or f"{settings.redis_url}/0"
    backend = settings.celery_result_backend or f"{settings.redis_url}/1"

    app = Celery(
        "knowgate",
        broker=broker,
        backend=backend,
        include=[
            "app.tasks.sync",
        ],
    )
    app.conf.update(
        # Serialization
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Time
        timezone="UTC",
        enable_utc=True,
        # Reliability
        task_acks_late=True,  # ack only after task completes (no lost tasks on kill)
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,  # one task per worker at a time (heavy sync)
        # Retries
        task_default_retry_delay=30,  # seconds
        task_default_max_retries=3,
        # Eager mode for tests (set in test conftest via env)
        task_always_eager=settings.celery_task_always_eager,
        task_eager_propagates=True,  # propagate exceptions in eager mode (test visibility)
        # Result TTL
        result_expires=3600,  # 1 hour
    )
    logger.info(
        "celery_app_built",
        broker_host=settings.redis_host,
        eager=settings.celery_task_always_eager,
    )
    return app


# Module-level singleton (workers import this)
celery_app = _make_celery()
