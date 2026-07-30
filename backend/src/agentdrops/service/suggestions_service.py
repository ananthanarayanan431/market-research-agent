"""Suggestions service: LLM-generated example research prompts for the idle chat state, cached
in Redis so repeat page loads don't each trigger a fresh LLM call.
"""

import json

from langchain_core.messages import SystemMessage
from redis.asyncio import Redis

from agentdrops.agents.llm import ainvoke_with_retry, build_llm
from agentdrops.agents.prompts import STARTER_SUGGESTIONS_PROMPT, get_today_str
from agentdrops.agents.schemas import StarterSuggestions
from agentdrops.config import Settings

_CACHE_KEY = "starter_suggestions"
_CACHE_TTL_SECONDS = 3600


class SuggestionsService:
    """Generates example research prompts for the idle chat state via the LLM, cache-asided
    against Redis for `_CACHE_TTL_SECONDS` — shared across every user, one LLM call per hour
    rather than one per page load."""

    def __init__(self, settings: Settings, redis: Redis) -> None:
        self._settings = settings
        self._redis = redis

    async def get_starter_prompts(self) -> list[str]:
        cached = await self._redis.get(_CACHE_KEY)
        if cached is not None:
            cached_prompts: list[str] = json.loads(cached)
            return cached_prompts

        llm = build_llm(self._settings, temperature=0.7).with_structured_output(
            StarterSuggestions
        )
        system = SystemMessage(content=STARTER_SUGGESTIONS_PROMPT.format(date=get_today_str()))
        result = await ainvoke_with_retry(llm, [system])
        assert isinstance(result, StarterSuggestions)

        await self._redis.set(_CACHE_KEY, json.dumps(result.prompts), ex=_CACHE_TTL_SECONDS)
        return result.prompts
