import anthropic
import httpx

from agentdrops.resilience.llm_retry import is_retryable_llm_error


def _status_error(
    cls: type[anthropic.APIStatusError], status_code: int
) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request, json={"error": {"message": "x"}})
    return cls("error", response=response, body=None)


def test_is_retryable_llm_error_rate_limit() -> None:
    assert is_retryable_llm_error(_status_error(anthropic.RateLimitError, 429)) is True


def test_is_retryable_llm_error_internal_server_error() -> None:
    assert is_retryable_llm_error(_status_error(anthropic.InternalServerError, 500)) is True


def test_is_retryable_llm_error_connection_error() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    assert is_retryable_llm_error(anthropic.APIConnectionError(request=request)) is True


def test_is_retryable_llm_error_bad_request_not_retried() -> None:
    assert is_retryable_llm_error(_status_error(anthropic.BadRequestError, 400)) is False


def test_is_retryable_llm_error_other_exception_not_retried() -> None:
    assert is_retryable_llm_error(ValueError("not anthropic")) is False
