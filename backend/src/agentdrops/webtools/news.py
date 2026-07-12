from typing import Any, ClassVar, cast

import httpx

from agentdrops.webtools.base import (
    RETRYABLE_HTTP,
    BaseSearchTool,
    SearchResult,
    SearchToolError,
    parse_iso_datetime,
)


class NewsApiSearchTool(BaseSearchTool):
    name: ClassVar[str] = "newsapi"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            payload = await self._call(query, max_results)
        except httpx.HTTPStatusError as exc:
            msg = f"HTTP {exc.response.status_code}: {exc.response.text}"
            raise SearchToolError(self.name, msg) from exc
        except httpx.TransportError as exc:
            raise SearchToolError(self.name, f"transport error: {exc}") from exc

        results: list[SearchResult] = []
        for item in payload.get("articles", [])[:max_results]:
            results.append(
                SearchResult(
                    tool_name=self.name,
                    title=item.get("title") or item["url"],
                    url=item["url"],
                    snippet=(item.get("description") or item.get("content") or "")[:1000],
                    published_at=parse_iso_datetime(item.get("publishedAt")),
                    score=None,
                )
            )
        return results

    @RETRYABLE_HTTP
    async def _call(self, query: str, max_results: int) -> dict[str, Any]:
        response = await self._client.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "apiKey": self._api_key,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": min(max_results, 100),
            },
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())
