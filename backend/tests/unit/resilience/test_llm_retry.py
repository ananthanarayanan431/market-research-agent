import httpx

from agentdrops.resilience.llm_retry import is_retryable_llm_error


class _FakeAPIError(Exception):
    """Stands in for any provider SDK's status-carrying error (openai/anthropic/google-genai)."""

    def __init__(self, status_code: int) -> None:
        super().__init__("error")
        self.status_code = status_code


class _FakeAPIConnectionError(Exception):
    """Mimics the `*APIConnectionError` naming convention shared across provider SDKs."""


def test_is_retryable_llm_error_rate_limit() -> None:
    assert is_retryable_llm_error(_FakeAPIError(429)) is True


def test_is_retryable_llm_error_server_errors() -> None:
    for status_code in (500, 502, 503, 504):
        assert is_retryable_llm_error(_FakeAPIError(status_code)) is True


def test_is_retryable_llm_error_bad_request_not_retried() -> None:
    assert is_retryable_llm_error(_FakeAPIError(400)) is False


def test_is_retryable_llm_error_connection_error_by_class_name() -> None:
    assert is_retryable_llm_error(_FakeAPIConnectionError()) is True


def test_is_retryable_llm_error_httpx_transport_error() -> None:
    assert is_retryable_llm_error(httpx.ConnectError("boom")) is True


def test_is_retryable_llm_error_other_exception_not_retried() -> None:
    assert is_retryable_llm_error(ValueError("unrelated")) is False
