from datetime import UTC, datetime
from typing import ClassVar

import pybreaker
import pytest

from agentdrops.webtools.base import (
    BaseSearchTool,
    SearchResult,
    SearchToolError,
    parse_epoch_seconds,
    parse_iso_datetime,
    wrap_http_errors,
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


async def test_wrap_http_errors_translates_circuit_breaker_error() -> None:
    with pytest.raises(SearchToolError) as exc_info:
        async with wrap_http_errors("exa"):
            raise pybreaker.CircuitBreakerError("breaker open")
    assert exc_info.value.tool_name == "exa"
    assert "circuit open" in str(exc_info.value)


async def test_wrap_http_errors_prefixes_circuit_breaker_message() -> None:
    with pytest.raises(SearchToolError) as exc_info:
        async with wrap_http_errors("reddit", prefix="token "):
            raise pybreaker.CircuitBreakerError("breaker open")
    assert str(exc_info.value) == "[reddit] token circuit open: reddit unavailable"


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
