"""All infra initialization steps (run from docker-compose init container OR dev).

Order:
1. DB schema (alembic upgrade head) — handled by separate `alembic` CLI call
2. Qdrant collection init (`chunks` with HNSW + payload indexes)
3. MinIO bucket init (`documents` with versioning)
4. Seed default data (admin user, roles, groups, settings)

Idempotent: re-runs are safe.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import get_session_factory
from scripts.init_helpers import (  # noqa: E402
    init_minio_bucket,
    init_qdrant_collection,
    seed_default_data,
)

logger = logging.getLogger(__name__)


async def run_all_init() -> None:
    """Run all non-DB init steps."""
    logger.info("init_starting")

    # 1. Qdrant collection
    try:
        await init_qdrant_collection()
    except Exception:
        logger.exception("init_qdrant_failed")
        raise

    # 2. MinIO bucket
    try:
        await init_minio_bucket()
    except Exception:
        logger.exception("init_minio_failed")
        raise

    # 3. Seed
    try:
        await seed_default_data()
    except Exception:
        logger.exception("init_seed_failed")
        raise

    logger.info("init_complete")


def main() -> None:
    """CLI entry: `python -m scripts.init` (or via `make init`)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(run_all_init())


if __name__ == "__main__":
    main()
