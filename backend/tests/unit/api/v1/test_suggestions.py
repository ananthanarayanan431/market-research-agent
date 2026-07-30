import pytest
from fastapi.testclient import TestClient

import agentdrops.service.suggestions_service as suggestions_service_module
from agentdrops.agents.schemas import StarterSuggestions
from tests.unit.agents.conftest import FakeChatModel


async def test_get_starter_suggestions_returns_llm_generated_prompts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeChatModel([StarterSuggestions(prompts=["A", "B", "C"])])
    monkeypatch.setattr(suggestions_service_module, "build_llm", lambda settings, **kw: llm)

    response = client.get("/v1/suggestions/starter")

    assert response.status_code == 200
    assert response.json()["data"]["prompts"] == ["A", "B", "C"]


async def test_get_starter_suggestions_uses_cache_on_second_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = 0

    def _build_llm(settings: object, **kw: object) -> FakeChatModel:
        nonlocal call_count
        call_count += 1
        return FakeChatModel([StarterSuggestions(prompts=["A", "B", "C"])])

    monkeypatch.setattr(suggestions_service_module, "build_llm", _build_llm)

    first = client.get("/v1/suggestions/starter")
    second = client.get("/v1/suggestions/starter")

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count == 1
