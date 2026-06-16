"""Async Qdrant client init + health check."""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    """Lazy-init singleton async Qdrant client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            grpc_port=settings.qdrant_grpc_port,
            api_key=settings.qdrant_api_key.get_secret_value() or None,
            timeout=30.0,
        )
        logger.info("qdrant_client_initialized", host=settings.qdrant_host, port=settings.qdrant_port)
    return _client


async def check_qdrant() -> bool:
    """Verify Qdrant is reachable. Returns True if cluster info works."""
    try:
        client = get_qdrant_client()
        await client.get_collections()
        return True
    except (UnexpectedResponse, Exception) as e:
        logger.error("qdrant_health_check_failed", error=str(e))
        return False


async def close_qdrant() -> None:
    """Close Qdrant client (for shutdown)."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
