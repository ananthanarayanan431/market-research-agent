import httpx
import pytest
from respx import MockRouter

from agentdrops.agents.contexthub.embeddings import EmbeddingClient


@pytest.mark.respx(base_url="https://api.openai.com/v1")
async def test_embed_returns_one_vector_per_input_text(respx_mock: MockRouter) -> None:
    respx_mock.post("/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2]},
                    {"embedding": [0.3, 0.4]},
                ]
            },
        )
    )
    async with httpx.AsyncClient() as http_client:
        client = EmbeddingClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="text-embedding-3-small",
            client=http_client,
        )
        vectors = await client.embed(["hello", "world"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


async def test_embed_empty_input_returns_empty_list() -> None:
    async with httpx.AsyncClient() as http_client:
        client = EmbeddingClient(
            api_key="test-key", base_url="https://api.openai.com/v1",
            model="text-embedding-3-small", client=http_client,
        )
        assert await client.embed([]) == []


@pytest.mark.respx(base_url="https://api.openai.com/v1")
async def test_embed_sends_model_and_bearer_auth(respx_mock: MockRouter) -> None:
    route = respx_mock.post("/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
    )
    async with httpx.AsyncClient() as http_client:
        client = EmbeddingClient(
            api_key="secret-key", base_url="https://api.openai.com/v1",
            model="text-embedding-3-small", client=http_client,
        )
        await client.embed(["hi"])

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-key"
    assert b'"model":"text-embedding-3-small"' in request.content
