import pybreaker
import pytest

from agentdrops.resilience.circuit_breaker import call_with_breaker, get_breaker


def test_get_breaker_returns_same_instance_for_same_name() -> None:
    breaker_a = get_breaker("test-cb-same-name")
    breaker_b = get_breaker("test-cb-same-name")
    assert breaker_a is breaker_b


def test_get_breaker_returns_different_instances_for_different_names() -> None:
    breaker_a = get_breaker("test-cb-name-a")
    breaker_b = get_breaker("test-cb-name-b")
    assert breaker_a is not breaker_b


def test_get_breaker_applies_configured_thresholds_on_first_creation() -> None:
    breaker = get_breaker("test-cb-thresholds", fail_max=2, reset_timeout=30)
    assert breaker.fail_max == 2
    assert breaker.reset_timeout == 30


async def test_call_with_breaker_returns_result_on_success() -> None:
    breaker = get_breaker("test-cb-success")

    async def succeed() -> str:
        return "ok"

    result = await call_with_breaker(breaker, succeed)
    assert result == "ok"


async def test_call_with_breaker_propagates_the_original_exception_below_threshold() -> None:
    breaker = get_breaker("test-cb-below-threshold", fail_max=3, reset_timeout=60)

    async def fail() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await call_with_breaker(breaker, fail)


async def test_call_with_breaker_opens_after_fail_max_failures() -> None:
    breaker = get_breaker("test-cb-opens", fail_max=2, reset_timeout=60)

    async def fail() -> str:
        raise RuntimeError("boom")

    # first failure: below threshold, original exception propagates
    with pytest.raises(RuntimeError):
        await call_with_breaker(breaker, fail)

    # second failure reaches fail_max=2 — pybreaker raises CircuitBreakerError
    # on this same tripping call rather than propagating RuntimeError
    with pytest.raises(pybreaker.CircuitBreakerError):
        await call_with_breaker(breaker, fail)

    # circuit stays open: further calls also short-circuit
    with pytest.raises(pybreaker.CircuitBreakerError):
        await call_with_breaker(breaker, fail)


async def test_call_with_breaker_open_circuit_does_not_invoke_the_function() -> None:
    breaker = get_breaker("test-cb-short-circuits", fail_max=1, reset_timeout=60)
    call_count = 0

    async def fail() -> str:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    # fail_max=1: the first failure both invokes func AND reaches the
    # threshold, so pybreaker raises CircuitBreakerError on this call too
    with pytest.raises(pybreaker.CircuitBreakerError):
        await call_with_breaker(breaker, fail)
    assert call_count == 1

    # circuit is now open: second call short-circuits without invoking func
    with pytest.raises(pybreaker.CircuitBreakerError):
        await call_with_breaker(breaker, fail)
    assert call_count == 1
