import pytest
from pydantic import ValidationError

from agentdrops.config import Settings


def test_settings_loads_required_fields_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "or-test")
    monkeypatch.setenv("EXA_API_KEY", "exa-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NEWSAPI_KEY", "news-test")
    monkeypatch.setenv("REDDIT_CLIENT_ID", "reddit-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "reddit-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/agentdrops")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_SECRET_KEY", "minioadmin")

    settings = Settings(_env_file=None)

    assert settings.llm_api_key == "or-test"
    assert settings.exa_api_key == "exa-test"
    assert settings.tavily_api_key == "tvly-test"
    assert settings.newsapi_key == "news-test"
    assert settings.reddit_client_id == "reddit-id"
    assert settings.reddit_client_secret == "reddit-secret"
    assert settings.reddit_user_agent == "agentdrops-market-research/0.1"
    assert settings.log_level == "INFO"


def test_settings_missing_required_field_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "LLM_API_KEY",
        "EXA_API_KEY",
        "TAVILY_API_KEY",
        "NEWSAPI_KEY",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "DATABASE_URL",
        "REDIS_URL",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "or-test")
    monkeypatch.setenv("EXA_API_KEY", "exa-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NEWSAPI_KEY", "news-test")
    monkeypatch.setenv("REDDIT_CLIENT_ID", "reddit-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "reddit-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/agentdrops")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_SECRET_KEY", "minioadmin")


def test_settings_rejects_unsupported_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "bogus")

    with pytest.raises(ValidationError, match="llm_provider must be one of"):
        Settings(_env_file=None)


def test_settings_accepts_supported_native_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "anthropic"
