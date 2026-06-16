"""Prometheus metrics for the KnowGate API + worker.

All custom metrics use the `kg_` prefix and follow Prometheus naming
conventions (`_total` for counters, `_seconds` for time histograms).

Label cardinality is bounded by design: `endpoint` is the FastAPI route
template (not the full path), `source` is one of ~10 known values, and
`model` is the LiteLLM model name (low cardinality). User IDs and
document IDs are NEVER used as label values (would explode cardinality).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# === API request metrics ===

# Histogram buckets cover 10ms..10s — 99% of API calls fall in this range.
_LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

REQUEST_COUNT = Counter(
    "kg_api_requests_total",
    "Total API requests by endpoint and status code.",
    ["endpoint", "status"],
)
REQUEST_DURATION = Histogram(
    "kg_api_request_duration_seconds",
    "API request duration in seconds by endpoint.",
    ["endpoint"],
    buckets=_LATENCY_BUCKETS,
)


# === LLM usage ===

LLM_TOKENS_TOTAL = Counter(
    "kg_llm_tokens_total",
    "LLM token usage by model and type (prompt|completion).",
    ["model", "type"],
)
LLM_COST_USD_TOTAL = Counter(
    "kg_llm_cost_usd_total",
    "Estimated LLM cost in USD by model (sum of per-call estimates).",
    ["model"],
)
LLM_REQUEST_DURATION = Histogram(
    "kg_llm_request_duration_seconds",
    "LLM request duration in seconds by model.",
    ["model"],
    buckets=_LATENCY_BUCKETS,
)


# === Sync / worker jobs ===

SYNC_JOBS_TOTAL = Counter(
    "kg_sync_jobs_total",
    "Sync jobs processed by source and outcome status.",
    ["source", "status"],
)
SYNC_JOB_DURATION = Histogram(
    "kg_sync_job_duration_seconds",
    "Sync job duration in seconds by source.",
    ["source"],
    buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0),
)


# === Query pipeline ===

QUERY_LATENCY = Histogram(
    "kg_query_latency_seconds",
    "End-to-end query pipeline latency by stage.",
    ["stage"],
    buckets=_LATENCY_BUCKETS,
)


# === Runtime state (gauges) ===

ACTIVE_SYNC_JOBS = Gauge(
    "kg_active_sync_jobs",
    "Number of sync jobs currently running across all workers.",
)
QUEUE_DEPTH = Gauge(
    "kg_queue_depth",
    "Number of pending jobs in a queue (label = queue name).",
    ["queue"],
)
SEMANTIC_CACHE_HITS = Gauge(
    "kg_semantic_cache_hits_total",
    "Cumulative count of semantic cache hits (monotonic gauge).",
)


__all__ = [
    "ACTIVE_SYNC_JOBS",
    "LLM_COST_USD_TOTAL",
    "LLM_REQUEST_DURATION",
    "LLM_TOKENS_TOTAL",
    "QUERY_LATENCY",
    "QUEUE_DEPTH",
    "REQUEST_COUNT",
    "REQUEST_DURATION",
    "SEMANTIC_CACHE_HITS",
    "SYNC_JOBS_TOTAL",
    "SYNC_JOB_DURATION",
]
