"""Single factory for the chat model, reused by every graph node (one config, one place)."""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import SecretStr

from agentdrops.config import Settings
from agentdrops.resilience.llm_retry import LLM_RETRY


def build_llm(settings: Settings, *, temperature: float = 0.0) -> BaseChatModel:
    """Build the chat model every agent node shares.

    Provider/wire-protocol is picked by `settings.llm_provider` and dispatched by langchain's
    `init_chat_model` — swapping backends is a config change, not a code change.
    """
    default_headers: dict[str, str] = {}
    if settings.llm_site_url:
        default_headers["HTTP-Referer"] = settings.llm_site_url
    if settings.llm_app_name:
        default_headers["X-Title"] = settings.llm_app_name

    try:
        return init_chat_model(
            settings.research_model,
            model_provider=settings.llm_provider,
            api_key=SecretStr(settings.llm_api_key),
            base_url=settings.llm_base_url,
            temperature=temperature,
            timeout=settings.llm_request_timeout_seconds,
            default_headers=default_headers or None,
        )
    except ImportError as exc:
        raise ImportError(
            f"llm_provider={settings.llm_provider!r} needs its SDK installed — "
            "run: pip install '.[providers]'"
        ) from exc


async def ainvoke_with_retry[T](runnable: Runnable[Any, T], llm_input: Any) -> T:
    """Invoke any LLM-backed runnable, retrying transient errors regardless of provider."""
    return await LLM_RETRY(runnable.ainvoke)(llm_input)
