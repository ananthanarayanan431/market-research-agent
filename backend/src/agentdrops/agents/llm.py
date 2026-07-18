"""Single factory for the Anthropic chat model, reused by every graph node (one model source)."""

from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from agentdrops.config import Settings


def build_llm(settings: Settings, *, temperature: float = 0.0) -> ChatAnthropic:
    """Build the Anthropic chat model every agent node shares (provider/model live in one place)."""
    return ChatAnthropic(
        model_name=settings.research_model,
        api_key=SecretStr(settings.anthropic_api_key),
        temperature=temperature,
        timeout=settings.llm_request_timeout_seconds,
        stop=None,
    )
