from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_LLM_PROVIDERS: frozenset[str] = frozenset({"openai", "anthropic", "google_genai"})
"""Provider keys we install SDKs for, retry-map, and test. See agents/llm.py for dispatch."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = "openai"
    """Wire protocol langchain's init_chat_model() dispatches on (see agents/llm.py).

    "openai" covers any OpenAI-wire-compatible gateway (OpenRouter, Together, Groq, vLLM, ...);
    point llm_base_url at the gateway. Switch to a native provider key (e.g. "anthropic",
    "google_genai") to bypass the gateway entirely — no code change either way. Must be one of
    SUPPORTED_LLM_PROVIDERS; native providers need the `providers` extra installed.
    """

    @field_validator("llm_provider")
    @classmethod
    def _validate_llm_provider(cls, value: str) -> str:
        if value not in SUPPORTED_LLM_PROVIDERS:
            allowed = ", ".join(sorted(SUPPORTED_LLM_PROVIDERS))
            raise ValueError(f"llm_provider must be one of: {allowed} (got {value!r})")
        return value

    llm_api_key: str
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_site_url: str | None = None
    """Optional HTTP-Referer sent to OpenRouter for their app-ranking dashboard."""
    llm_app_name: str | None = None
    """Optional X-Title sent to OpenRouter for their app-ranking dashboard."""
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

    research_model: str = "anthropic/claude-sonnet-5"
    """OpenRouter model id used by every agent node (single source, see agents/llm.py)."""
    max_researcher_iterations: int = 6
    """Supervisor loop cap: forces END after this many supervisor turns."""
    max_concurrent_researchers: int = 3
    """Max research sub-agents the supervisor may fan out concurrently per turn."""
    max_tool_call_iterations: int = 5
    """Research sub-agent ReAct loop cap: forces compression after this many tool-call rounds."""
    llm_request_timeout_seconds: float = 60.0
    """Timeout for every LLM call, so a stalled API request can't hang a worker forever."""


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
