from collections.abc import AsyncIterator

import httpx
import pytest

from agentdrops.resilience.circuit_breaker import _breakers


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture(autouse=True)
def _reset_circuit_breakers() -> None:
    _breakers.clear()
