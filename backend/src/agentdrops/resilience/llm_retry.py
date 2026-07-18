import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRYABLE_ERROR_SUFFIXES = ("APIConnectionError", "APITimeoutError")


def is_retryable_llm_error(exc: BaseException) -> bool:
    """Provider-agnostic retry check: no openai/anthropic/google SDK imports.

    Every provider's SDK (openai, anthropic, google-genai, ...) raises an exception exposing a
    `status_code` attribute on rate-limit/server errors, and a connection/timeout error whose
    class name ends in APIConnectionError/APITimeoutError — duck-type on that shape instead of
    importing every provider's exception hierarchy (mirrors resilience/http_retry.py).
    """
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and status_code in _RETRYABLE_STATUS_CODES:
        return True
    if exc.__class__.__name__.endswith(_RETRYABLE_ERROR_SUFFIXES):
        return True
    return isinstance(exc, httpx.TransportError)


LLM_RETRY = retry(
    retry=retry_if_exception(is_retryable_llm_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
