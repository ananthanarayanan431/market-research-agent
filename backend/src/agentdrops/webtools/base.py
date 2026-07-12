from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import ClassVar

import httpx
import pybreaker
from pydantic import BaseModel


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
    except pybreaker.CircuitBreakerError as exc:
        raise SearchToolError(tool_name, f"{prefix}circuit open: {tool_name} unavailable") from exc


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
