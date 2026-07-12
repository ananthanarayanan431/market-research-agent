import httpx

from agentdrops.config import Settings
from agentdrops.webtools.base import BaseSearchTool
from agentdrops.webtools.exa import ExaSearchTool
from agentdrops.webtools.news import NewsApiSearchTool
from agentdrops.webtools.reddit import RedditSearchTool
from agentdrops.webtools.tavily import TavilySearchTool


def build_search_tools(settings: Settings, client: httpx.AsyncClient) -> list[BaseSearchTool]:
    return [
        ExaSearchTool(api_key=settings.exa_api_key, client=client),
        TavilySearchTool(api_key=settings.tavily_api_key, client=client),
        NewsApiSearchTool(api_key=settings.newsapi_key, client=client),
        RedditSearchTool(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
            client=client,
        ),
    ]
