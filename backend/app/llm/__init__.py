"""LLM gateway package (LiteLLM proxy client).

KnowGate talks to a single OpenAI-compatible endpoint (the LiteLLM
proxy) regardless of whether the underlying model is OpenAI, Ollama,
or a self-hosted inference server. The proxy is configured in
`deploy/litellm-config.yaml` to fall back from `gpt-4o-mini` to
`ollama/llama3` when the primary is unavailable.

This package owns:
- `client.py` — the HTTP client (httpx async)
- `prompts.py` — the system prompt + answer formatting rules
- `circuit_breaker.py` — primary → fallback model with retry/backoff

Workers and the API both call into this package. Workers via
`reembed_all_task` and (in future) eval; the API via the query
endpoint.
"""

from app.llm.circuit_breaker import CircuitBreaker, CircuitState
from app.llm.client import LLMClient, LLMResult
from app.llm.prompts import KG_PROMPT_VERSION, build_answer_prompt

__all__ = [
    "KG_PROMPT_VERSION",
    "CircuitBreaker",
    "CircuitState",
    "LLMClient",
    "LLMResult",
    "build_answer_prompt",
]
