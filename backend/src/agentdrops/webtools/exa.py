from typing import Any, ClassVar, cast

import httpx

from agentdrops.webtools.base import (
    RETRYABLE_HTTP,
    BaseSearchTool,
    SearchResult,
    parse_iso_datetime,
    wrap_http_errors,
)


class ExaSearchTool(BaseSearchTool):
    name: ClassVar[str] = "exa"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with wrap_http_errors(self.name):
            payload = await self._call(query, max_results)
            results: list[SearchResult] = []
            for item in payload.get("results", [])[:max_results]:
                results.append(
                    SearchResult(
                        tool_name=self.name,
                        title=item.get("title") or item["url"],
                        url=item["url"],
                        snippet=(item.get("text") or item.get("summary") or "")[:1000],
                        published_at=parse_iso_datetime(item.get("publishedDate")),
                        score=item.get("score"),
                    )
                )
        return results

    @RETRYABLE_HTTP
    async def _call(self, query: str, max_results: int) -> dict[str, Any]:
        response = await self._client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": self._api_key, "Content-Type": "application/json"},
            json={
                "query": query,
                "numResults": max_results,
                "contents": {"text": True, "summary": True},
            },
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())
