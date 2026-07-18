from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from agentdrops.agents.llm import build_llm
from tests.unit.agents.conftest import make_settings


def test_build_llm_dispatches_to_configured_provider() -> None:
    settings = make_settings(research_model="anthropic/claude-sonnet-5")

    llm = build_llm(settings)

    assert isinstance(llm, ChatOpenAI)
    assert str(llm.openai_api_base) == "https://openrouter.ai/api/v1"
    assert llm.model_name == "anthropic/claude-sonnet-5"


def test_build_llm_dispatches_to_native_anthropic_provider() -> None:
    """Proves the switch is config-only: a non-default llm_provider dispatches to a different
    langchain chat-model class entirely, with no code change in build_llm()."""
    settings = make_settings(llm_provider="anthropic", research_model="claude-sonnet-5")

    llm = build_llm(settings)

    assert isinstance(llm, ChatAnthropic)


def test_build_llm_sends_optional_ranking_headers() -> None:
    settings = make_settings(
        llm_site_url="https://example.com",
        llm_app_name="agentdrops",
    )

    llm = build_llm(settings)

    assert isinstance(llm, ChatOpenAI)
    headers = llm.default_headers or {}
    assert headers["HTTP-Referer"] == "https://example.com"
    assert headers["X-Title"] == "agentdrops"


def test_build_llm_omits_headers_when_not_configured() -> None:
    llm = build_llm(make_settings())

    assert isinstance(llm, ChatOpenAI)
    assert not (llm.default_headers or {})
