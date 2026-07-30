import json

from fakeredis.aioredis import FakeRedis

from agentdrops.agents.schemas import StarterSuggestions
from agentdrops.service.suggestions_service import _CACHE_KEY, SuggestionsService
from tests.unit.agents.conftest import FakeChatModel, make_settings


async def test_get_starter_prompts_calls_llm_on_cache_miss_and_caches_result(
    monkeypatch: object,
) -> None:
    llm = FakeChatModel([StarterSuggestions(prompts=["A", "B", "C"])])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.service.suggestions_service.build_llm", lambda settings, **kw: llm
    )
    redis = FakeRedis(decode_responses=True)
    service = SuggestionsService(make_settings(), redis)

    prompts = await service.get_starter_prompts()

    assert prompts == ["A", "B", "C"]
    assert json.loads(await redis.get(_CACHE_KEY)) == ["A", "B", "C"]


async def test_get_starter_prompts_returns_cached_value_without_calling_llm(
    monkeypatch: object,
) -> None:
    def _fail(*_a: object, **_kw: object) -> None:
        raise AssertionError("build_llm should not be called on a cache hit")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.service.suggestions_service.build_llm", _fail
    )
    redis = FakeRedis(decode_responses=True)
    await redis.set(_CACHE_KEY, json.dumps(["Cached A", "Cached B"]))
    service = SuggestionsService(make_settings(), redis)

    prompts = await service.get_starter_prompts()

    assert prompts == ["Cached A", "Cached B"]
