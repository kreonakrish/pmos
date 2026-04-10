"""Unit tests for the circuit breaker."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


async def _success():
    return "ok"


async def _fail():
    raise RuntimeError("downstream error")


@pytest.mark.asyncio
async def test_closed_state_passes_calls():
    """Fresh circuit breaker is CLOSED and lets calls through."""
    cb = CircuitBreaker("test-cb", failure_threshold=5, timeout_sec=30)
    result = await cb.call(_success)
    assert result == "ok"
    assert cb.state == CircuitBreaker.STATE_CLOSED


@pytest.mark.asyncio
async def test_transitions_to_open_after_threshold_failures():
    """5 consecutive failures → state becomes OPEN."""
    cb = CircuitBreaker("test-open", failure_threshold=5, timeout_sec=30)

    for _ in range(5):
        with pytest.raises(RuntimeError):
            await cb.call(_fail)

    assert cb.state == CircuitBreaker.STATE_OPEN
    assert cb.failure_count >= 5


@pytest.mark.asyncio
async def test_open_state_fails_fast_without_calling_downstream():
    """In OPEN state, calls raise CircuitBreakerOpenError immediately."""
    cb = CircuitBreaker("test-fast-fail", failure_threshold=3, timeout_sec=9999)

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(_fail)

    assert cb.state == CircuitBreaker.STATE_OPEN

    called = []

    async def downstream():
        called.append(True)
        return "reached"

    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(downstream)

    assert called == [], "Downstream must NOT be called when circuit is OPEN"


@pytest.mark.asyncio
async def test_transitions_to_half_open_after_timeout():
    """After cb_timeout_sec elapses, state becomes HALF_OPEN on next call attempt."""
    cb = CircuitBreaker("test-half-open", failure_threshold=2, timeout_sec=0)
    # timeout_sec=0 means any elapsed time qualifies

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cb.call(_fail)

    assert cb.state == CircuitBreaker.STATE_OPEN

    # Force last_failure_time to past so timeout check passes
    cb.last_failure_time = time.monotonic() - 1

    # Next call: circuit should enter HALF_OPEN, then succeed → CLOSED
    result = await cb.call(_success)
    assert result == "ok"
    assert cb.state == CircuitBreaker.STATE_CLOSED


@pytest.mark.asyncio
async def test_success_in_half_open_closes_circuit():
    """One success in HALF_OPEN → back to CLOSED with reset counters."""
    cb = CircuitBreaker("test-recover", failure_threshold=2, timeout_sec=0)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cb.call(_fail)

    cb.last_failure_time = time.monotonic() - 1
    cb.state = CircuitBreaker.STATE_HALF_OPEN  # force half-open directly

    await cb.call(_success)

    assert cb.state == CircuitBreaker.STATE_CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_failure_in_half_open_reopens_circuit():
    """One failure in HALF_OPEN → back to OPEN."""
    cb = CircuitBreaker("test-reopen", failure_threshold=2, timeout_sec=30)
    cb.state = CircuitBreaker.STATE_HALF_OPEN
    cb.failure_count = 2

    with pytest.raises(RuntimeError):
        await cb.call(_fail)

    assert cb.state == CircuitBreaker.STATE_OPEN
