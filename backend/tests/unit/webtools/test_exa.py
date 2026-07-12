import httpx
import pytest
import respx

from agentdrops.webtools.base import SearchToolError
from agentdrops.webtools.exa import ExaSearchTool


@respx.mock
async def test_exa_search_returns_parsed_results(http_client: httpx.AsyncClient) -> None:
    respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "AI note-taking market overview",
                        "url": "https://example.com/article",
                        "text": "The market for AI note-taking apps is growing.",
                        "publishedDate": "2026-06-01T00:00:00Z",
                        "score": 0.87,
                    }
                ]
            },
        )
    )
    tool = ExaSearchTool(api_key="test-key", client=http_client)

    results = await tool.search("AI note-taking apps", max_results=5)

    assert len(results) == 1
    assert results[0].tool_name == "exa"
    assert results[0].title == "AI note-taking market overview"
    assert results[0].url == "https://example.com/article"
    assert results[0].snippet.startswith("The market for AI note-taking apps")
    assert results[0].score == 0.87


@respx.mock
async def test_exa_search_raises_search_tool_error_on_http_error(
    http_client: httpx.AsyncClient,
) -> None:
    respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(401, json={"error": "invalid key"})
    )
    tool = ExaSearchTool(api_key="bad-key", client=http_client)

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("AI note-taking apps")

    assert exc_info.value.tool_name == "exa"


@respx.mock
async def test_exa_search_raises_search_tool_error_on_malformed_response(
    http_client: httpx.AsyncClient,
) -> None:
    respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(200, json={"results": [{"title": "t"}]})
    )
    tool = ExaSearchTool(api_key="test-key", client=http_client)

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("AI note-taking apps")

    assert exc_info.value.tool_name == "exa"


@respx.mock
async def test_exa_search_retries_on_transient_5xx_then_succeeds(
    http_client: httpx.AsyncClient,
) -> None:
    route = respx.post("https://api.exa.ai/search")
    route.side_effect = [
        httpx.Response(503, json={"error": "unavailable"}),
        httpx.Response(
            200,
            json={"results": [{"title": "t", "url": "https://example.com", "text": "body"}]},
        ),
    ]
    tool = ExaSearchTool(api_key="test-key", client=http_client)

    results = await tool.search("query")

    assert len(results) == 1
    assert route.call_count == 2
