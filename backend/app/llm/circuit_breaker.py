"""Circuit breaker for LLM provider fallback (primary → fallback).

When the primary model (e.g. `gpt-4o-mini`) returns 5xx or 429 too
often, we open the circuit and route all traffic to the fallback
model (e.g. `ollama/llama3`). After a cool-down, we let one request
through (HALF_OPEN) and resume normal operation if it succeeds.

The breaker state is process-local (not in Redis) — a single app
instance has one breaker. For multi-instance deployments the same
behavior repeats per instance; that's fine because the failure
threshold is short and the fallback model is stateless.

State machine:

    CLOSED ──(N failures in window)──> OPEN
    OPEN   ──(cool-down elapsed)──> HALF_OPEN
    HALF_OPEN ──(success)──> CLOSED
    HALF_OPEN ──(failure)──> OPEN

The half-open state lets a single probe request through; if it
fails, we go back to OPEN and restart the cool-down.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

from app.logging import get_logger

logger = get_logger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class CircuitBreaker:
    """Tracks failures per model and decides which model to use next.

    Args:
        primary: the default model name (e.g. "gpt-4o-mini")
        fallback: the fallback model name (e.g. "ollama/llama3")
        failure_threshold: open the circuit after this many consecutive
            failures in the current window
        cool_down_seconds: how long to stay in OPEN before probing
    """

    primary: str
    fallback: str
    failure_threshold: int = 5
    cool_down_seconds: float = 60.0

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0
    half_open_in_flight: bool = False
    # For tests / observability
    total_failures: int = 0
    total_successes: int = 0
    fallback_used_count: int = 0

    def model_to_call(self) -> str:
        """Decide which model to use for the NEXT request.

        Returns `primary` when the circuit is CLOSED (or HALF_OPEN with
        no probe in flight), and `fallback` when OPEN.
        """
        if self.state == CircuitState.CLOSED:
            return self.primary
        if self.state == CircuitState.OPEN:
            # Have we waited long enough to probe?
            if time.monotonic() - self.opened_at >= self.cool_down_seconds:
                self.state = CircuitState.HALF_OPEN
                self.half_open_in_flight = True
                logger.info("circuit_half_open", primary=self.primary)
                return self.primary
            self.fallback_used_count += 1
            return self.fallback
        # HALF_OPEN
        if self.half_open_in_flight:
            # A probe is in flight; route everything else to fallback
            self.fallback_used_count += 1
            return self.fallback
        # We were in HALF_OPEN with no in-flight; let the next caller probe
        self.half_open_in_flight = True
        return self.primary

    def record_success(self, model_used: str) -> None:
        """Call this after a successful LLM call.

        A success in CLOSED resets the failure counter. A success in
        HALF_OPEN closes the circuit (we recovered).
        """
        self.total_successes += 1
        self.consecutive_failures = 0

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.half_open_in_flight = False
            logger.info("circuit_closed", primary=self.primary)
        # If we used the fallback while the breaker was open, count it
        # but don't change state (the primary isn't proven healthy yet).
        if model_used == self.fallback and self.state == CircuitState.CLOSED:
            # Used fallback while healthy? Operator might be testing —
            # just count it, don't open the circuit.
            self.fallback_used_count += 1

    def record_failure(self, model_used: str) -> None:
        """Call this after a failed LLM call (5xx, 429, timeout)."""
        self.total_failures += 1
        self.consecutive_failures += 1

        if self.state == CircuitState.HALF_OPEN:
            # Probe failed — go back to OPEN
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()
            self.half_open_in_flight = False
            logger.warning("circuit_reopened", primary=self.primary)
            return

        if self.state == CircuitState.CLOSED and self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()
            logger.warning(
                "circuit_opened",
                primary=self.primary,
                fallback=self.fallback,
                failures=self.consecutive_failures,
            )

    def reset(self) -> None:
        """Force-reset the breaker to CLOSED. For tests only."""
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.opened_at = 0.0
        self.half_open_in_flight = False
        self.total_failures = 0
        self.total_successes = 0
        self.fallback_used_count = 0


__all__ = ["CircuitBreaker", "CircuitState"]
