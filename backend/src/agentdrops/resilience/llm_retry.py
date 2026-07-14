import anthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

_RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
)


def is_retryable_llm_error(exc: BaseException) -> bool:
    return isinstance(exc, _RETRYABLE_ERRORS)


LLM_RETRY = retry(
    retry=retry_if_exception(is_retryable_llm_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
