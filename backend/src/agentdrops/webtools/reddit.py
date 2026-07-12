from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

import httpx

from agentdrops.webtools.base import (
    RETRYABLE_HTTP,
    BaseSearchTool,
    SearchResult,
    SearchToolError,
    parse_epoch_seconds,
)


class RedditSearchTool(BaseSearchTool):
    name: ClassVar[str] = "reddit"

    def __init__(
        self, client_id: str, client_secret: str, user_agent: str, client: httpx.AsyncClient
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._client = client
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        token = await self._get_access_token()
        try:
            payload = await self._call(query, max_results, token)
        except httpx.HTTPStatusError as exc:
            msg = f"HTTP {exc.response.status_code}: {exc.response.text}"
            raise SearchToolError(self.name, msg) from exc
        except httpx.TransportError as exc:
            raise SearchToolError(self.name, f"transport error: {exc}") from exc

        results: list[SearchResult] = []
        for child in payload.get("data", {}).get("children", [])[:max_results]:
            post = child.get("data", {})
            permalink = post.get("permalink", "")
            results.append(
                SearchResult(
                    tool_name=self.name,
                    title=post.get("title", ""),
                    url=f"https://reddit.com{permalink}" if permalink else post.get("url", ""),
                    snippet=(post.get("selftext") or "")[:1000],
                    published_at=parse_epoch_seconds(post.get("created_utc")),
                    score=post.get("score"),
                )
            )
        return results

    async def _get_access_token(self) -> str:
        if self._token and self._token_expires_at and datetime.now(UTC) < self._token_expires_at:
            return self._token

        try:
            payload = await self._fetch_token()
        except httpx.HTTPStatusError as exc:
            msg = f"token HTTP {exc.response.status_code}: {exc.response.text}"
            raise SearchToolError(self.name, msg) from exc
        except httpx.TransportError as exc:
            raise SearchToolError(self.name, f"token transport error: {exc}") from exc

        self._token = payload["access_token"]
        self._token_expires_at = datetime.now(UTC) + timedelta(seconds=payload["expires_in"] - 60)
        return self._token

    @RETRYABLE_HTTP
    async def _fetch_token(self) -> dict[str, Any]:
        response = await self._client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self._user_agent},
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    @RETRYABLE_HTTP
    async def _call(self, query: str, max_results: int, token: str) -> dict[str, Any]:
        response = await self._client.get(
            "https://oauth.reddit.com/search",
            params={"q": query, "limit": max_results, "sort": "relevance"},
            headers={"Authorization": f"Bearer {token}", "User-Agent": self._user_agent},
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())
