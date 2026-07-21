from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentdrops.main as main_module
from tests.unit.agents.conftest import make_settings


class _StubGraph:
    """App startup needs a graph object; health doesn't drive it."""

    async def astream(
        self, _inputs: dict, config: dict, stream_mode: list[str]
    ) -> AsyncIterator[tuple[str, dict]]:
        return
        yield  # pragma: no cover - makes this an async generator

    async def aget_state(self, config: dict) -> Any:
        raise NotImplementedError


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        main_module, "build_market_researcher", lambda settings, client: _StubGraph()
    )
    with TestClient(main_module.app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": {"status": "ok"}}
