from collections.abc import Awaitable, Callable
from typing import Any

import pybreaker

_breakers: dict[str, pybreaker.CircuitBreaker] = {}


def get_breaker(
    name: str, *, fail_max: int = 5, reset_timeout: int = 60
) -> pybreaker.CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = pybreaker.CircuitBreaker(
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            name=name,
        )
    return _breakers[name]


async def call_with_breaker[T](
    breaker: pybreaker.CircuitBreaker,
    func: Callable[..., Awaitable[T]],
    *args: Any,
    **kwargs: Any,
) -> T:
    result: T = await breaker.call_async(func, *args, **kwargs)  # type: ignore[no-untyped-call]
    return result
