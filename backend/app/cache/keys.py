"""Redis key naming convention (single source of truth, avoid key collisions)."""

from __future__ import annotations

# All keys prefixed with `kg:` (KnowGate) and namespace:
#   kg:query:embed:{hash}        — query embedding cache
#   kg:query:result:{hash}        — semantic cache (LLM response)
#   kg:rate:user:{user_id}:{window}   — rate limit counter
#   kg:rate:ip:{ip}:{window}      — rate limit per IP
#   kg:session:{jti}              — session / token revocation
#   kg:oauth:state:{state}        — OAuth state (CSRF)
#   kg:hot:queries                — sorted set (hot topics widget)
#   kg:hot:zset:{period}          — sorted set for time-period leaderboard


def query_embed_key(text_hash: str) -> str:
    """Cache key for query embedding (text_hash = sha256 of query text)."""
    return f"kg:query:embed:{text_hash}"


def query_result_key(query_hash: str, filter_hash: str) -> str:
    """Semantic cache key for LLM response (query + filter hash)."""
    return f"kg:query:result:{query_hash}:{filter_hash}"


def rate_limit_user_key(user_id: str, window_seconds: int) -> str:
    """Rate limit counter (sliding window per user)."""
    return f"kg:rate:user:{user_id}:{window_seconds}"


def rate_limit_ip_key(ip: str, window_seconds: int) -> str:
    """Rate limit counter (sliding window per IP)."""
    return f"kg:rate:ip:{ip}:{window_seconds}"


def session_jti_key(jti: str) -> str:
    """Session/JTI revocation marker (set on logout, checked per request)."""
    return f"kg:session:{jti}"


def oauth_state_key(state: str) -> str:
    """OAuth state token (CSRF protection, 5-min TTL)."""
    return f"kg:oauth:state:{state}"


def hot_queries_key() -> str:
    """Sorted set of recent query counts (for hot topics widget)."""
    return "kg:hot:queries"


__all__ = [
    "query_embed_key",
    "query_result_key",
    "rate_limit_user_key",
    "rate_limit_ip_key",
    "session_jti_key",
    "oauth_state_key",
    "hot_queries_key",
]
