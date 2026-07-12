from typing import Any, ClassVar, cast

import httpx

from agentdrops.resilience.circuit_breaker import call_with_breaker, get_breaker
from agentdrops.resilience.http_retry import HTTP_RETRY
from agentdrops.webtools.base import BaseSearchTool, SearchResult, wrap_http_errors


class TavilySearchTool(BaseSearchTool):
    name: ClassVar[str] = "tavily"

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient,
        *,
        breaker_fail_max: int = 5,
        breaker_reset_timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._breaker = get_breaker(
            self.name, fail_max=breaker_fail_max, reset_timeout=breaker_reset_timeout
        )

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with wrap_http_errors(self.name):
            payload = await call_with_breaker(self._breaker, self._call, query, max_results)
            results: list[SearchResult] = []
            for item in payload.get("results", [])[:max_results]:
                results.append(
                    SearchResult(
                        tool_name=self.name,
                        title=item.get("title") or item["url"],
                        url=item["url"],
                        snippet=(item.get("content") or "")[:1000],
                        published_at=None,
                        score=item.get("score"),
                    )
                )
        return results

    @HTTP_RETRY
    async def _call(self, query: str, max_results: int) -> dict[str, Any]:
        response = await self._client.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
            },
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())
