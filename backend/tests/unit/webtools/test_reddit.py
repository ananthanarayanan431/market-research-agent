import httpx
import pytest
import respx

from agentdrops.webtools.base import SearchToolError
from agentdrops.webtools.reddit import RedditSearchTool


def _token_route() -> respx.Route:
    return respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
    )


@respx.mock
async def test_reddit_search_returns_parsed_results(http_client: httpx.AsyncClient) -> None:
    _token_route()
    respx.get("https://oauth.reddit.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "data": {
                                "title": "Anyone tried the new AI note app?",
                                "selftext": "Curious if it's worth switching.",
                                "permalink": "/r/productivity/comments/abc123/thread/",
                                "created_utc": 1751371200.0,
                                "score": 42,
                            }
                        }
                    ]
                }
            },
        )
    )
    tool = RedditSearchTool(
        client_id="cid",
        client_secret="csecret",
        user_agent="agentdrops-test/0.1",
        client=http_client,
    )

    results = await tool.search("AI note-taking apps", max_results=5)

    assert len(results) == 1
    assert results[0].tool_name == "reddit"
    assert results[0].title == "Anyone tried the new AI note app?"
    assert results[0].url == "https://reddit.com/r/productivity/comments/abc123/thread/"
    assert results[0].snippet == "Curious if it's worth switching."
    assert results[0].score == 42
    assert results[0].published_at is not None


@respx.mock
async def test_reddit_search_reuses_cached_token_across_calls(
    http_client: httpx.AsyncClient,
) -> None:
    token_route = _token_route()
    respx.get("https://oauth.reddit.com/search").mock(
        return_value=httpx.Response(200, json={"data": {"children": []}})
    )
    tool = RedditSearchTool(
        client_id="cid",
        client_secret="csecret",
        user_agent="agentdrops-test/0.1",
        client=http_client,
    )

    await tool.search("query one")
    await tool.search("query two")

    assert token_route.call_count == 1


@respx.mock
async def test_reddit_search_raises_search_tool_error_on_token_failure(
    http_client: httpx.AsyncClient,
) -> None:
    respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    tool = RedditSearchTool(
        client_id="bad", client_secret="bad", user_agent="agentdrops-test/0.1", client=http_client
    )

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("query")

    assert exc_info.value.tool_name == "reddit"


@respx.mock
async def test_reddit_search_raises_search_tool_error_when_circuit_open(
    http_client: httpx.AsyncClient,
) -> None:
    respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(500, json={"error": "down"})
    )
    tool = RedditSearchTool(
        client_id="cid",
        client_secret="csecret",
        user_agent="agentdrops-test/0.1",
        client=http_client,
        breaker_fail_max=1,
    )

    with pytest.raises(SearchToolError):
        await tool.search("first call trips the breaker")

    # as with the other tools' circuit-open tests: the first call already
    # made HTTP_RETRY's attempts against the token endpoint before the
    # breaker tripped, so assert the SECOND call adds no further calls
    # rather than asserting an absolute 0.
    token_route = respx.post("https://www.reddit.com/api/v1/access_token")
    calls_before_second_attempt = token_route.call_count
    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("second call should short-circuit")

    assert "circuit open" in str(exc_info.value)
    assert token_route.call_count == calls_before_second_attempt
