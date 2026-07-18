import httpx

from agentdrops.config import Settings
from agentdrops.webtools import build_search_tools
from agentdrops.webtools.exa import ExaSearchTool
from agentdrops.webtools.news import NewsApiSearchTool
from agentdrops.webtools.reddit import RedditSearchTool
from agentdrops.webtools.tavily import TavilySearchTool


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="or-test",
        exa_api_key="exa-test",
        tavily_api_key="tvly-test",
        newsapi_key="news-test",
        reddit_client_id="reddit-id",
        reddit_client_secret="reddit-secret",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentdrops",
        redis_url="redis://localhost:6379/0",
        minio_endpoint="localhost:9000",
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin",
    )


async def test_build_search_tools_returns_all_four_tools_in_order() -> None:
    async with httpx.AsyncClient() as client:
        tools = build_search_tools(_settings(), client)

    assert [type(tool) for tool in tools] == [
        ExaSearchTool,
        TavilySearchTool,
        NewsApiSearchTool,
        RedditSearchTool,
    ]
    assert [tool.name for tool in tools] == ["exa", "tavily", "newsapi", "reddit"]
