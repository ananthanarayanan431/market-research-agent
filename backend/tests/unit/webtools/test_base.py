from datetime import UTC, datetime
from typing import ClassVar

import httpx

from agentdrops.webtools.base import (
    BaseSearchTool,
    SearchResult,
    SearchToolError,
    is_retryable_http_error,
    parse_epoch_seconds,
    parse_iso_datetime,
)


class _EchoSearchTool(BaseSearchTool):
    name: ClassVar[str] = "echo"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [
            SearchResult(
                tool_name=self.name, title=query, url="https://example.com", snippet=query
            )
        ]


async def test_base_search_tool_subclass_returns_search_results() -> None:
    tool = _EchoSearchTool()
    results = await tool.search("market trends")
    assert results == [
        SearchResult(
            tool_name="echo",
            title="market trends",
            url="https://example.com",
            snippet="market trends",
        )
    ]


def test_search_tool_error_message_includes_tool_name() -> None:
    error = SearchToolError("exa", "rate limited")
    assert str(error) == "[exa] rate limited"
    assert error.tool_name == "exa"


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


def test_parse_iso_datetime_parses_valid_string() -> None:
    assert parse_iso_datetime("2026-07-01T12:00:00Z") == datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def test_parse_iso_datetime_returns_none_for_none() -> None:
    assert parse_iso_datetime(None) is None


def test_parse_iso_datetime_returns_none_for_invalid_string() -> None:
    assert parse_iso_datetime("not-a-date") is None


def test_parse_epoch_seconds_parses_valid_value() -> None:
    assert parse_epoch_seconds(1751371200.0) == datetime.fromtimestamp(1751371200.0, tz=UTC)


def test_parse_epoch_seconds_returns_none_for_none() -> None:
    assert parse_epoch_seconds(None) is None
