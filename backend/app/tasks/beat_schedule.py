"""Celery Beat schedule — periodic sync polling.

The Beat process is a separate container in `deploy/docker-compose.yml`.
To enable Beat, add `-S django` or pass `--beat` to the worker command.
In our setup, the `beat` service runs `celery -A app.celery_app beat`.
"""

from __future__ import annotations

from app.celery_app import celery_app
from app.config import get_settings

settings = get_settings()

celery_app.conf.beat_schedule = {
    "sync-all-sources-every-5-min": {
        "task": "sync_all_sources",
        # Run every `sync_interval_minutes` (default 5)
        "schedule": float(settings.sync_interval_minutes * 60.0),
    },
}
