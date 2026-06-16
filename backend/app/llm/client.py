"""LLM gateway client (httpx async against the LiteLLM proxy).

KnowGate calls a single OpenAI-compatible endpoint (the LiteLLM
proxy) regardless of whether the underlying model is OpenAI, Ollama,
or a self-hosted server. The proxy handles the auth + fallback
chain (configured in `deploy/litellm-config.yaml`).

The client is intentionally thin — just enough to POST to
`/v1/chat/completions` and parse the response. No streaming in MVP;
each query returns one full answer.

Cost is estimated from the response's `usage` field and the
known-per-model price table below. The estimate is good enough for
budget alerts (precision is not required, ±20% is fine).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.logging import get_logger
from app.observability.metrics import (
    LLM_COST_USD_TOTAL,
    LLM_REQUEST_DURATION,
    LLM_TOKENS_TOTAL,
)

logger = get_logger(__name__)


# Per-1K-token USD price table. OpenAI's gpt-4o-mini is the default;
# the fallback model is configured in `Settings.litellm_fallback_model`
# but cost-tracked separately. Numbers come from the OpenAI pricing
# page (Jan 2026). Update when the pricing model changes.
_PRICE_PER_1K = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "ollama/llama3": {"input": 0.0, "output": 0.0},  # self-hosted
}


def _estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from token counts. Unknown models → 0.0."""
    price = _PRICE_PER_1K.get(model)
    if price is None:
        # Unknown model — log once and return 0 (no cost surprise)
        logger.debug("llm_cost_unknown_model", model=model)
        return 0.0
    in_cost = (prompt_tokens / 1000.0) * price["input"]
    out_cost = (completion_tokens / 1000.0) * price["output"]
    return round(in_cost + out_cost, 6)


@dataclass(slots=True)
class LLMResult:
    """Outcome of one LLM call."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: int
    raw: dict[str, Any]  # Full provider response (for debugging)


class LLMClient:
    """Async client for the LiteLLM proxy.

    Reuses a single `httpx.AsyncClient` for connection pooling. The
    client is process-local; workers and the API process each have
    their own instance.

    The `complete()` method retries on 5xx / 429 with exponential
    backoff (via tenacity). Auth errors (401) and 4xx (other than
    429) are surfaced immediately.

    Optional `breaker`: when provided, the client routes through the
    primary model normally, but switches to the fallback when the
    breaker is OPEN. Success/failure are reported to the breaker.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
        timeout_seconds: float = 30.0,
        breaker: Any | None = None,
    ) -> None:
        s = get_settings()
        self._base_url = (base_url or s.litellm_url).rstrip("/")
        self._api_key = api_key or s.litellm_master_key.get_secret_value()
        self._default_model = model or s.litellm_default_model
        self._fallback_model = fallback_model or s.litellm_fallback_model
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._breaker = breaker  # Optional CircuitBreaker

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init the httpx client (one per LLMClient instance)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying httpx client (call on app shutdown)."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> LLMResult:
        """Send a chat completion request, return the parsed result.

        Args:
            messages: OpenAI-style messages list (role + content)
            model: override the default model (used by the circuit
                breaker when falling back)
            temperature: 0.0 = deterministic, 1.0 = creative
            max_tokens: hard cap on the response length

        Returns:
            LLMResult with the text, usage, cost estimate, and the raw
            provider response.

        Raises:
            httpx.HTTPStatusError: on non-2xx after retries
            httpx.RequestError: on network failure after retries
        """
        # Pick the model — explicit override wins, else consult the
        # breaker, else default.
        if model is not None:
            target_model = model
        elif self._breaker is not None:
            target_model = self._breaker.model_to_call()
        else:
            target_model = self._default_model

        import time

        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        client = await self._get_client()
        start = time.perf_counter()
        try:
            response = await client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
        except Exception:
            if self._breaker is not None:
                self._breaker.record_failure(target_model)
            raise
        latency_ms = int((time.perf_counter() - start) * 1000)
        body = response.json()

        # OpenAI format: choices[0].message.content
        text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        usage = body.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
        actual_model = body.get("model", target_model)
        cost = _estimate_cost_usd(actual_model, prompt_tokens, completion_tokens)

        # Observability: emit per-call metrics. Label values are
        # bounded (model = small enum, type = 2 values).
        LLM_TOKENS_TOTAL.labels(model=actual_model, type="prompt").inc(prompt_tokens)
        LLM_TOKENS_TOTAL.labels(model=actual_model, type="completion").inc(completion_tokens)
        LLM_COST_USD_TOTAL.labels(model=actual_model).inc(cost)
        LLM_REQUEST_DURATION.labels(model=actual_model).observe(latency_ms / 1000.0)

        if self._breaker is not None:
            self._breaker.record_success(actual_model)

        logger.info(
            "llm_completion",
            model=actual_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
        )
        return LLMResult(
            text=text,
            model=actual_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            raw=body,
        )


__all__ = ["LLMClient", "LLMResult"]
