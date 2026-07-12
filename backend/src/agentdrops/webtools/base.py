from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import ClassVar

import httpx
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


class SearchResult(BaseModel):
    tool_name: str
    title: str
    url: str
    snippet: str
    published_at: datetime | None = None
    score: float | None = None


class SearchToolError(Exception):
    def __init__(self, tool_name: str, message: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"[{tool_name}] {message}")


class BaseSearchTool(ABC):
    name: ClassVar[str]

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...


def is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


RETRYABLE_HTTP = retry(
    retry=retry_if_exception(is_retryable_http_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    reraise=True,
)


@asynccontextmanager
async def wrap_http_errors(tool_name: str, *, prefix: str = "") -> AsyncIterator[None]:
    try:
        yield
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        msg = f"{prefix}HTTP {exc.response.status_code}: {body}"
        raise SearchToolError(tool_name, msg) from exc
    except httpx.TransportError as exc:
        raise SearchToolError(tool_name, f"{prefix}transport error: {exc}") from exc
    except KeyError as exc:
        raise SearchToolError(tool_name, f"{prefix}malformed response: missing key {exc}") from exc


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_epoch_seconds(value: float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=UTC)
