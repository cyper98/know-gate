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
    # Generic
    "cache_delete",
    "cache_get_json",
    "cache_set_json",
    "cache_ttl",
    "check_ip_rate_limit",
    # Client
    "check_redis",
    "check_user_rate_limit",
    "close_redis",
    "get_hot_queries",
    # Specific helpers
    "get_query_embed",
    "get_query_result",
    "get_redis_client",
    # Keys
    "hot_queries_key",
    "is_jti_revoked",
    "oauth_state_key",
    "pop_oauth_state",
    "query_embed_key",
    "query_result_key",
    "rate_limit_incr",
    "rate_limit_ip_key",
    "rate_limit_user_key",
    "revoke_jti",
    "session_jti_key",
    "set_oauth_state",
    "set_query_embed",
    "set_query_result",
    "track_query",
]
