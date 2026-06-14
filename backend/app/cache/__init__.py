"""Cache package (Redis: queue + cache + rate limit + session)."""

from app.cache.client import check_redis, close_redis, get_redis_client
from app.cache.helpers import (
    cache_delete,
    cache_get_json,
    cache_set_json,
    cache_ttl,
    check_ip_rate_limit,
    check_user_rate_limit,
    get_hot_queries,
    get_query_embed,
    get_query_result,
    is_jti_revoked,
    pop_oauth_state,
    rate_limit_incr,
    revoke_jti,
    set_oauth_state,
    set_query_embed,
    set_query_result,
    track_query,
)
from app.cache.keys import (
    hot_queries_key,
    oauth_state_key,
    query_embed_key,
    query_result_key,
    rate_limit_ip_key,
    rate_limit_user_key,
    session_jti_key,
)

__all__ = [
    # Client
    "check_redis",
    "close_redis",
    "get_redis_client",
    # Generic
    "cache_delete",
    "cache_get_json",
    "cache_set_json",
    "cache_ttl",
    "rate_limit_incr",
    # Specific helpers
    "get_query_embed",
    "set_query_embed",
    "get_query_result",
    "set_query_result",
    "check_user_rate_limit",
    "check_ip_rate_limit",
    "revoke_jti",
    "is_jti_revoked",
    "set_oauth_state",
    "pop_oauth_state",
    "track_query",
    "get_hot_queries",
    # Keys
    "hot_queries_key",
    "oauth_state_key",
    "query_embed_key",
    "query_result_key",
    "rate_limit_ip_key",
    "rate_limit_user_key",
    "session_jti_key",
]
