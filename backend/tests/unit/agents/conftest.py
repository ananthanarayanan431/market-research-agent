from agentdrops.config import Settings


def make_settings(**overrides: object) -> Settings:
    """Build a Settings instance with test-friendly defaults, no real .env file needed."""
    defaults: dict[str, object] = {
        "_env_file": None,
        "anthropic_api_key": "sk-ant-test",
        "exa_api_key": "exa-test",
        "tavily_api_key": "tvly-test",
        "newsapi_key": "news-test",
        "reddit_client_id": "reddit-id",
        "reddit_client_secret": "reddit-secret",
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/agentdrops",
        "redis_url": "redis://localhost:6379/0",
        "minio_endpoint": "localhost:9000",
        "minio_access_key": "minioadmin",
        "minio_secret_key": "minioadmin",
        "max_researcher_iterations": 2,
        "max_concurrent_researchers": 2,
        "max_tool_call_iterations": 2,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class FakeChatModel:
    """Minimal stand-in for a LangChain chat model: scripted responses, no network calls."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.bound_tools: list[object] | None = None

    def bind_tools(self, tools: list[object]) -> "FakeChatModel":
        self.bound_tools = tools
        return self

    def with_structured_output(self, schema: object) -> "FakeChatModel":
        return self

    async def ainvoke(self, _messages: object) -> object:
        return self._responses.pop(0)
