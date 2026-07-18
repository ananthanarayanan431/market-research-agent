from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str
    exa_api_key: str
    tavily_api_key: str
    newsapi_key: str
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str = "agentdrops-market-research/0.1"

    database_url: str
    redis_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str

    log_level: str = "INFO"

    research_model: str = "claude-sonnet-5"
    """Anthropic model id used by every agent node (single source, see agents/llm.py)."""
    max_researcher_iterations: int = 6
    """Supervisor loop cap: forces END after this many supervisor turns."""
    max_concurrent_researchers: int = 3
    """Max research sub-agents the supervisor may fan out concurrently per turn."""
    max_tool_call_iterations: int = 5
    """Research sub-agent ReAct loop cap: forces compression after this many tool-call rounds."""
    llm_request_timeout_seconds: float = 60.0
    """Timeout for every Anthropic call, so a stalled API request can't hang a worker forever."""


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
