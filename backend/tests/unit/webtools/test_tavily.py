import httpx
import pytest
import respx

from agentdrops.webtools.base import SearchToolError
from agentdrops.webtools.tavily import TavilySearchTool


@respx.mock
async def test_tavily_search_returns_parsed_results(http_client: httpx.AsyncClient) -> None:
    respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "EV charging market report",
                        "url": "https://example.com/ev",
                        "content": "EV charging infrastructure is expanding rapidly.",
                        "score": 0.91,
                    }
                ]
            },
        )
    )
    tool = TavilySearchTool(api_key="tvly-test", client=http_client)

    results = await tool.search("EV charging", max_results=5)

    assert len(results) == 1
    assert results[0].tool_name == "tavily"
    assert results[0].title == "EV charging market report"
    assert results[0].url == "https://example.com/ev"
    assert results[0].snippet.startswith("EV charging infrastructure")
    assert results[0].score == 0.91


@respx.mock
async def test_tavily_search_sends_bearer_auth_header(http_client: httpx.AsyncClient) -> None:
    route = respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    tool = TavilySearchTool(api_key="tvly-test", client=http_client)

    await tool.search("EV charging")

    assert route.calls.last.request.headers["Authorization"] == "Bearer tvly-test"


@respx.mock
async def test_tavily_search_raises_search_tool_error_on_http_error(
    http_client: httpx.AsyncClient,
) -> None:
    respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(401, json={"error": "bad key"})
    )
    tool = TavilySearchTool(api_key="bad-key", client=http_client)

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("EV charging")

    assert exc_info.value.tool_name == "tavily"
