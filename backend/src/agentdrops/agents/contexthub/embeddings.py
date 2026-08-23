"""Thin client for an OpenAI-wire-compatible /embeddings endpoint — independent of
agents/llm.py's chat-model dispatch, since embeddings aren't a chat-model call. Used both at
ingest time (embed each chunk) and at query time (embed the search query)."""

from typing import Any, cast

import httpx

from agentdrops.resilience.http_retry import HTTP_RETRY


class EmbeddingClient:
    def __init__(self, api_key: str, base_url: str, model: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = await self._call(texts)
        return [item["embedding"] for item in payload["data"]]

    @HTTP_RETRY
    async def _call(self, texts: list[str]) -> dict[str, Any]:
        response = await self._client.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": texts},
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())
