"""Unit tests for the LLM circuit breaker."""

from __future__ import annotations

import time

from app.llm.circuit_breaker import CircuitBreaker, CircuitState


def test_starts_closed() -> None:
    cb = CircuitBreaker(primary="gpt-4o-mini", fallback="ollama/llama3")
    assert cb.state == CircuitState.CLOSED
    assert cb.model_to_call() == "gpt-4o-mini"


def test_opens_after_threshold_failures() -> None:
    cb = CircuitBreaker(
        primary="gpt-4o-mini", fallback="ollama/llama3", failure_threshold=3
    )
    cb.record_failure("gpt-4o-mini")
    cb.record_failure("gpt-4o-mini")
    assert cb.state == CircuitState.CLOSED
    cb.record_failure("gpt-4o-mini")
    assert cb.state == CircuitState.OPEN
    assert cb.model_to_call() == "ollama/llama3"  # fallback


def test_success_resets_failure_counter() -> None:
    cb = CircuitBreaker(primary="p", fallback="f", failure_threshold=3)
    cb.record_failure("p")
    cb.record_failure("p")
    cb.record_success("p")
    assert cb.consecutive_failures == 0
    # Now 2 more failures must not open (we reset on success)
    cb.record_failure("p")
    cb.record_failure("p")
    assert cb.state == CircuitState.CLOSED


def test_open_circuit_uses_fallback() -> None:
    cb = CircuitBreaker(
        primary="p", fallback="f", failure_threshold=1, cool_down_seconds=60.0
    )
    cb.record_failure("p")
    assert cb.state == CircuitState.OPEN
    # Two more calls — both should go to fallback
    assert cb.model_to_call() == "f"
    assert cb.model_to_call() == "f"


def test_open_to_half_open_after_cooldown() -> None:
    cb = CircuitBreaker(
        primary="p", fallback="f", failure_threshold=1, cool_down_seconds=0.05
    )
    cb.record_failure("p")
    assert cb.state == CircuitState.OPEN
    time.sleep(0.06)
    # Next call transitions to HALF_OPEN + uses primary
    assert cb.model_to_call() == "p"
    assert cb.state == CircuitState.HALF_OPEN


def test_half_open_success_closes_circuit() -> None:
    cb = CircuitBreaker(
        primary="p", fallback="f", failure_threshold=1, cool_down_seconds=0.05
    )
    cb.record_failure("p")
    time.sleep(0.06)
    cb.model_to_call()  # move to HALF_OPEN
    cb.record_success("p")
    assert cb.state == CircuitState.CLOSED


def test_half_open_failure_reopens_circuit() -> None:
    cb = CircuitBreaker(
        primary="p", fallback="f", failure_threshold=1, cool_down_seconds=0.05
    )
    cb.record_failure("p")
    time.sleep(0.06)
    cb.model_to_call()  # move to HALF_OPEN
    cb.record_failure("p")
    assert cb.state == CircuitState.OPEN
    # Restart cool-down
    assert time.monotonic() - cb.opened_at < 1.0


def test_half_open_routes_concurrent_to_fallback() -> None:
    """While a probe is in flight, other callers see the fallback."""
    cb = CircuitBreaker(
        primary="p", fallback="f", failure_threshold=1, cool_down_seconds=0.05
    )
    cb.record_failure("p")
    time.sleep(0.06)
    assert cb.model_to_call() == "p"  # probe takes primary
    # Subsequent callers get fallback (probe in flight)
    assert cb.model_to_call() == "f"
    assert cb.model_to_call() == "f"


def test_reset_returns_to_closed() -> None:
    cb = CircuitBreaker(primary="p", fallback="f", failure_threshold=1)
    cb.record_failure("p")
    assert cb.state == CircuitState.OPEN
    cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb.consecutive_failures == 0
