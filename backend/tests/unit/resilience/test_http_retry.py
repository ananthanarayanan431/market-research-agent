import httpx

from agentdrops.resilience.http_retry import is_retryable_http_error


def test_is_retryable_http_error_transport_error() -> None:
    assert is_retryable_http_error(httpx.ConnectError("boom")) is True


def test_is_retryable_http_error_5xx() -> None:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError("error", request=request, response=response)
    assert is_retryable_http_error(exc) is True


def test_is_retryable_http_error_4xx_not_retried() -> None:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(404, request=request)
    exc = httpx.HTTPStatusError("error", request=request, response=response)
    assert is_retryable_http_error(exc) is False


def test_is_retryable_http_error_other_exception_not_retried() -> None:
    assert is_retryable_http_error(ValueError("not http")) is False
