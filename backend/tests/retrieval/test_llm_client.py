"""Unit tests for the LLM client + cost estimation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.llm import client as client_mod
from app.llm.client import LLMClient, LLMResult


def _mock_response(json_body: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_body)
    resp.raise_for_status = MagicMock()
    return resp


def test_cost_estimate_known_model() -> None:
    """gpt-4o-mini at 1000 input + 500 output: $0.00015 + $0.0003 = $0.00045."""
    cost = client_mod._estimate_cost_usd(
        "gpt-4o-mini", prompt_tokens=1000, completion_tokens=500
    )
    assert cost == pytest.approx(0.00045, abs=1e-6)


def test_cost_estimate_ollama_is_zero() -> None:
    cost = client_mod._estimate_cost_usd(
        "ollama/llama3", prompt_tokens=10000, completion_tokens=5000
    )
    assert cost == 0.0


def test_cost_estimate_unknown_model_is_zero() -> None:
    cost = client_mod._estimate_cost_usd(
        "future-model", prompt_tokens=100, completion_tokens=100
    )
    assert cost == 0.0


@pytest.mark.asyncio
async def test_complete_parses_openai_response() -> None:
    """Mocked httpx response: verify text, tokens, model, cost extracted."""
    body = {
        "model": "gpt-4o-mini",
        "choices": [{"message": {"content": "Hello back"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    c = LLMClient()
    # Mock the internal httpx client
    fake_httpx = MagicMock()
    fake_httpx.is_closed = False
    fake_httpx.post = AsyncMock(return_value=_mock_response(body))
    c._client = fake_httpx

    result = await c.complete(
        [{"role": "user", "content": "Hi"}],
        model="gpt-4o-mini",
    )
    assert isinstance(result, LLMResult)
    assert result.text == "Hello back"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.total_tokens == 15
    assert result.cost_usd > 0
    assert result.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_complete_uses_breaker_when_provided() -> None:
    """With a closed breaker, the model comes from the breaker."""
    from app.llm.circuit_breaker import CircuitBreaker

    breaker = CircuitBreaker(primary="primary", fallback="fallback")
    body = {
        "model": "primary",
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    c = LLMClient(breaker=breaker)
    fake_httpx = MagicMock()
    fake_httpx.is_closed = False
    fake_httpx.post = AsyncMock(return_value=_mock_response(body))
    c._client = fake_httpx

    await c.complete([{"role": "user", "content": "x"}])
    # Breaker saw a success
    assert breaker.total_successes == 1


@pytest.mark.asyncio
async def test_complete_records_failure_on_5xx() -> None:
    """A 500 from the provider counts as a breaker failure."""
    from app.llm.circuit_breaker import CircuitBreaker, CircuitState

    breaker = CircuitBreaker(primary="p", fallback="f", failure_threshold=1)
    c = LLMClient(breaker=breaker)
    fake_httpx = MagicMock()
    fake_httpx.is_closed = False

    # Build a real httpx.Response so raise_for_status actually does something
    request = httpx.Request("POST", "http://test/v1/chat/completions")
    err_response = httpx.Response(500, request=request)
    fake_httpx.post = AsyncMock(return_value=err_response)
    c._client = fake_httpx

    with pytest.raises(httpx.HTTPStatusError):
        await c.complete([{"role": "user", "content": "x"}])

    assert breaker.consecutive_failures == 1
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_aclose_releases_client() -> None:
    c = LLMClient()
    fake_httpx = MagicMock()
    fake_httpx.is_closed = False
    fake_httpx.aclose = AsyncMock()
    c._client = fake_httpx
    await c.aclose()
    fake_httpx.aclose.assert_awaited_once()
    assert c._client is None
