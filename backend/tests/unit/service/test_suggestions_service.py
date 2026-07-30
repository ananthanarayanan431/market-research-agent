import json

from fakeredis.aioredis import FakeRedis

from agentdrops.agents.schemas import StarterSuggestions
from agentdrops.service.suggestions_service import (
    _CACHE_KEY,
    _FAILURE_TTL_SECONDS,
    SuggestionsService,
)
from tests.unit.agents.conftest import FakeChatModel, make_settings


class _RaisingChatModel:
    """Minimal stand-in for a LangChain chat model whose structured-output call always fails,
    e.g. a provider outage or unparseable response."""

    def with_structured_output(self, schema: object) -> "_RaisingChatModel":
        return self

    async def ainvoke(self, _messages: object) -> object:
        raise RuntimeError("provider is down")


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


async def test_get_starter_prompts_caches_empty_list_with_short_ttl_on_llm_failure(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.service.suggestions_service.build_llm",
        lambda settings, **kw: _RaisingChatModel(),
    )
    redis = FakeRedis(decode_responses=True)
    service = SuggestionsService(make_settings(), redis)

    prompts = await service.get_starter_prompts()

    assert prompts == []
    cached = await redis.get(_CACHE_KEY)
    assert cached is not None
    assert json.loads(cached) == []
    ttl = await redis.ttl(_CACHE_KEY)
    assert 0 < ttl <= _FAILURE_TTL_SECONDS


async def test_get_starter_prompts_returns_cached_empty_list_without_calling_llm_again(
    monkeypatch: object,
) -> None:
    def _fail(*_a: object, **_kw: object) -> None:
        raise AssertionError("build_llm should not be called while the failure cache is warm")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.service.suggestions_service.build_llm", _fail
    )
    redis = FakeRedis(decode_responses=True)
    await redis.set(_CACHE_KEY, json.dumps([]), ex=_FAILURE_TTL_SECONDS)
    service = SuggestionsService(make_settings(), redis)

    prompts = await service.get_starter_prompts()

    assert prompts == []
