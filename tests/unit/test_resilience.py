import asyncio

import pytest

from stc_framework.errors import (
    BulkheadFull,
    CircuitBreakerOpen,
    LLMUnavailable,
    RetryExhausted,
)
from stc_framework.resilience.bulkhead import Bulkhead
from stc_framework.resilience.circuit import Circuit, get_circuit
from stc_framework.resilience.fallback import run_with_fallback
from stc_framework.resilience.retry import with_retry


@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}

    async def fn():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise LLMUnavailable(message="fail", retryable=True)
        return "ok"

    result = await with_retry(fn, downstream="test", max_attempts=5, base_delay=0.0)
    assert result == "ok"
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_retry_gives_up_on_non_retryable():
    async def fn():
        raise LLMUnavailable(message="nope", retryable=False)

    with pytest.raises(LLMUnavailable):
        await with_retry(fn, downstream="test", max_attempts=5, base_delay=0.0)


@pytest.mark.asyncio
async def test_retry_exhausted_on_unknown_transient():
    async def fn():
        raise TimeoutError("slow")

    with pytest.raises(RetryExhausted):
        await with_retry(fn, downstream="test", max_attempts=2, base_delay=0.0)


@pytest.mark.asyncio
async def test_circuit_opens_after_failures():
    c = Circuit("test", fail_max=2, reset_timeout=30.0)

    async def fail():
        raise LLMUnavailable(message="boom")

    with pytest.raises(LLMUnavailable):
        await c.call(fail)
    with pytest.raises(LLMUnavailable):
        await c.call(fail)
    # Third call should see open breaker
    with pytest.raises(CircuitBreakerOpen):
        await c.call(fail)


@pytest.mark.asyncio
async def test_fallback_recovers_on_first_fallback():
    async def primary():
        raise LLMUnavailable(message="primary down", retryable=True)

    async def fb():
        return "ok"

    result = await run_with_fallback(primary, [fb], label="test")
    assert result == "ok"


@pytest.mark.asyncio
async def test_fallback_does_not_try_on_non_retryable():
    async def primary():
        raise LLMUnavailable(message="stop", retryable=False)

    called = {"n": 0}

    async def fb():
        called["n"] += 1
        return "fallback"

    with pytest.raises(LLMUnavailable):
        await run_with_fallback(primary, [fb], label="test")
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_bulkhead_blocks_when_full():
    bulkhead = Bulkhead("test", limit=1)

    async with bulkhead.acquire():
        with pytest.raises(BulkheadFull):
            async with bulkhead.acquire(timeout=0.05):
                pass
