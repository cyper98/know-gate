"""Observability package: tracing, metrics, logging integrations.

Public entrypoints:
- setup_tracing(): install OpenTelemetry TracerProvider + instrumentations
- metrics: Prometheus counters, histograms, gauges
"""

from app.observability.metrics import (
    ACTIVE_SYNC_JOBS,
    LLM_COST_USD_TOTAL,
    LLM_REQUEST_DURATION,
    LLM_TOKENS_TOTAL,
    QUERY_LATENCY,
    QUEUE_DEPTH,
    REQUEST_COUNT,
    REQUEST_DURATION,
    SEMANTIC_CACHE_HITS,
    SYNC_JOBS_TOTAL,
)
from app.observability.tracing import setup_tracing

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
    "setup_tracing",
]
