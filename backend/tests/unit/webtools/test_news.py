import httpx
import pytest
import respx

from agentdrops.webtools.base import SearchToolError
from agentdrops.webtools.news import NewsApiSearchTool


@respx.mock
async def test_news_search_returns_parsed_results(http_client: httpx.AsyncClient) -> None:
    respx.get("https://newsapi.org/v2/everything").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "totalResults": 1,
                "articles": [
                    {
                        "title": "AI note-taking startup raises Series A",
                        "url": "https://example.com/news",
                        "description": "A new entrant raises funding.",
                        "publishedAt": "2026-06-15T09:30:00Z",
                    }
                ],
            },
        )
    )
    tool = NewsApiSearchTool(api_key="news-test", client=http_client)

    results = await tool.search("AI note-taking apps", max_results=5)

    assert len(results) == 1
    assert results[0].tool_name == "newsapi"
    assert results[0].title == "AI note-taking startup raises Series A"
    assert results[0].snippet == "A new entrant raises funding."
    assert results[0].published_at is not None


@respx.mock
async def test_news_search_sends_api_key_as_query_param(http_client: httpx.AsyncClient) -> None:
    route = respx.get("https://newsapi.org/v2/everything").mock(
        return_value=httpx.Response(200, json={"status": "ok", "totalResults": 0, "articles": []})
    )
    tool = NewsApiSearchTool(api_key="news-test", client=http_client)

    await tool.search("AI note-taking apps")

    assert route.calls.last.request.url.params["apiKey"] == "news-test"


@respx.mock
async def test_news_search_raises_search_tool_error_on_http_error(
    http_client: httpx.AsyncClient,
) -> None:
    respx.get("https://newsapi.org/v2/everything").mock(
        return_value=httpx.Response(401, json={"status": "error", "message": "bad key"})
    )
    tool = NewsApiSearchTool(api_key="bad-key", client=http_client)

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("AI note-taking apps")

    assert exc_info.value.tool_name == "newsapi"
