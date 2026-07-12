# Backend Foundations & Web Search Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `backend/` Python project (`src/agentdrops` package) with production-grade config/logging foundations, and implement the four external web-search clients (Exa, Tavily, NewsAPI, Reddit) behind a shared `BaseSearchTool` interface, each independently unit-tested against mocked HTTP.

**Architecture:** A `backend/` directory holding a `src/agentdrops` package. `agentdrops.config.Settings` (pydantic-settings) is the single source of runtime configuration; `agentdrops.logging` provides structured JSON logging correlated by `run_id`. `agentdrops.webtools` holds one module per search provider, each implementing `BaseSearchTool.search(query, max_results) -> list[SearchResult]`, with shared retry/parsing helpers in `webtools/base.py` and a `webtools/registry.py` factory that builds the configured tool list from `Settings`. This is Plan 1 of 4 for the deep research market agent (see `docs/superpowers/specs/2026-07-12-deepresearch-market-agent-design.md`); later plans build the LangGraph research pipeline, the FastAPI/arq/Postgres/MinIO service layer, and the Next.js frontend on top of this package.

**Tech Stack:** Python 3.12, `httpx` (async HTTP), `tenacity` (retry/backoff), `pydantic` v2 + `pydantic-settings`, `structlog`, `pytest` + `pytest-asyncio` + `respx` (HTTP mocking), `ruff`, `mypy --strict`, `uv` for dependency management.

## Global Constraints

- Python 3.12+, `mypy --strict` must pass with zero errors — no untyped defs anywhere in `src/agentdrops`.
- `ruff check` must pass with zero violations.
- Every external HTTP call goes through the shared `RETRYABLE_HTTP` tenacity decorator from `webtools/base.py` — no ad-hoc retry logic per tool.
- No secrets hardcoded anywhere — all configuration flows through `agentdrops.config.Settings`, sourced from environment variables / `.env`.
- All I/O boundaries (search results, config) are Pydantic v2 models — no bare dicts crossing module boundaries.
- All tool clients are async (`httpx.AsyncClient`), constructed with an injected client instance (never create a client per call) for connection reuse and testability.

---

## File Structure

```
backend/
  pyproject.toml
  src/agentdrops/
    __init__.py
    config.py
    logging.py
    webtools/
      __init__.py
      base.py            # SearchResult, SearchToolError, BaseSearchTool, retry + parse helpers
      exa.py              # ExaSearchTool
      tavily.py           # TavilySearchTool
      news.py              # NewsApiSearchTool
      reddit.py            # RedditSearchTool
      registry.py           # build_search_tools()
  tests/
    unit/
      test_config.py
      test_logging.py
      test_registry.py
      webtools/
        conftest.py         # shared http_client fixture
        test_base.py
        test_exa.py
        test_tavily.py
        test_news.py
        test_reddit.py
```

---

### Task 1: Backend project scaffold + Settings

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/agentdrops/__init__.py`
- Create: `backend/src/agentdrops/config.py`
- Create: `backend/.gitignore`
- Test: `backend/tests/unit/test_config.py`

**Interfaces:**
- Produces: `agentdrops.config.Settings` (pydantic-settings `BaseSettings`) with fields `anthropic_api_key: str`, `exa_api_key: str`, `tavily_api_key: str`, `newsapi_key: str`, `reddit_client_id: str`, `reddit_client_secret: str`, `reddit_user_agent: str = "agentdrops-market-research/0.1"`, `database_url: str`, `redis_url: str`, `minio_endpoint: str`, `minio_access_key: str`, `minio_secret_key: str`, `log_level: str = "INFO"`. Produces `agentdrops.config.get_settings() -> Settings` (lru-cached accessor).

- [ ] **Step 1: Create the backend project skeleton**

```bash
mkdir -p backend/src/agentdrops/webtools
mkdir -p backend/tests/unit/webtools
touch backend/src/agentdrops/__init__.py
touch backend/src/agentdrops/webtools/__init__.py
touch backend/tests/unit/__init__.py
touch backend/tests/unit/webtools/__init__.py
```

- [ ] **Step 2: Write `backend/pyproject.toml`**

```toml
[project]
name = "agentdrops"
version = "0.1.0"
description = "Agentdrops deep research market agent backend"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "tenacity>=8.2",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "structlog>=24.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "ruff>=0.5",
    "mypy>=1.10",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentdrops"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "ASYNC"]

[tool.mypy]
python_version = "3.12"
strict = true
mypy_path = "src"

[[tool.mypy.overrides]]
module = "respx.*"
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 3: Write `backend/.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
.env
uv.lock
```

- [ ] **Step 4: Install dependencies**

```bash
cd backend
uv sync --extra dev
```

- [ ] **Step 5: Write the failing test**

```python
# backend/tests/unit/test_config.py
import pytest
from pydantic import ValidationError

from agentdrops.config import Settings


def test_settings_loads_required_fields_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("EXA_API_KEY", "exa-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NEWSAPI_KEY", "news-test")
    monkeypatch.setenv("REDDIT_CLIENT_ID", "reddit-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "reddit-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/agentdrops")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_SECRET_KEY", "minioadmin")

    settings = Settings(_env_file=None)

    assert settings.anthropic_api_key == "sk-ant-test"
    assert settings.exa_api_key == "exa-test"
    assert settings.tavily_api_key == "tvly-test"
    assert settings.newsapi_key == "news-test"
    assert settings.reddit_client_id == "reddit-id"
    assert settings.reddit_client_secret == "reddit-secret"
    assert settings.reddit_user_agent == "agentdrops-market-research/0.1"
    assert settings.log_level == "INFO"


def test_settings_missing_required_field_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "ANTHROPIC_API_KEY",
        "EXA_API_KEY",
        "TAVILY_API_KEY",
        "NEWSAPI_KEY",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "DATABASE_URL",
        "REDIS_URL",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.config'`

- [ ] **Step 7: Write `backend/src/agentdrops/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str
    exa_api_key: str
    tavily_api_key: str
    newsapi_key: str
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str = "agentdrops-market-research/0.1"

    database_url: str
    redis_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add backend/pyproject.toml backend/.gitignore backend/src backend/tests
git commit -m "feat(backend): scaffold agentdrops package with Settings config"
```

---

### Task 2: Structured logging

**Files:**
- Create: `backend/src/agentdrops/logging.py`
- Test: `backend/tests/unit/test_logging.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `agentdrops.logging.configure_logging(level: str = "INFO") -> None`, `agentdrops.logging.get_logger(name: str) -> structlog.stdlib.BoundLogger`, `agentdrops.logging.bind_run_id(run_id: str) -> contextlib.AbstractContextManager[None]` (used as `with bind_run_id(run_id): ...`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_logging.py
import json

import pytest

from agentdrops.logging import bind_run_id, configure_logging, get_logger


def test_configure_logging_emits_json_with_bound_run_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO")
    logger = get_logger("test")

    with bind_run_id("run-123"):
        logger.info("research_started", topic="AI note-taking apps")

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])

    assert payload["event"] == "research_started"
    assert payload["run_id"] == "run-123"
    assert payload["topic"] == "AI note-taking apps"
    assert payload["level"] == "info"


def test_bind_run_id_unbinds_after_context_exits(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO")
    logger = get_logger("test")

    with bind_run_id("run-123"):
        pass
    logger.info("after_context")

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert "run_id" not in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_logging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.logging'`

- [ ] **Step 3: Write `backend/src/agentdrops/logging.py`**

```python
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import structlog

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def configure_logging(level: str = "INFO") -> None:
    numeric_level = _LEVEL_MAP.get(level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


@contextmanager
def bind_run_id(run_id: str) -> Iterator[None]:
    structlog.contextvars.bind_contextvars(run_id=run_id)
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars("run_id")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_logging.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/logging.py backend/tests/unit/test_logging.py
git commit -m "feat(backend): add structured JSON logging with run_id binding"
```

---

### Task 3: `webtools` base interface (`SearchResult`, `SearchToolError`, `BaseSearchTool`, retry/parse helpers)

**Files:**
- Create: `backend/src/agentdrops/webtools/base.py`
- Test: `backend/tests/unit/webtools/test_base.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2.
- Produces:
  - `agentdrops.webtools.base.SearchResult` — Pydantic model: `tool_name: str`, `title: str`, `url: str`, `snippet: str`, `published_at: datetime | None = None`, `score: float | None = None`.
  - `agentdrops.webtools.base.SearchToolError(Exception)` — constructed as `SearchToolError(tool_name: str, message: str)`, exposes `.tool_name: str`, `str(error) == f"[{tool_name}] {message}"`.
  - `agentdrops.webtools.base.BaseSearchTool` — ABC with `name: ClassVar[str]` and abstract `async def search(self, query: str, max_results: int = 5) -> list[SearchResult]`.
  - `agentdrops.webtools.base.is_retryable_http_error(exc: BaseException) -> bool`.
  - `agentdrops.webtools.base.RETRYABLE_HTTP` — a `tenacity.retry` decorator (3 attempts, exponential backoff, retries on `is_retryable_http_error`, `reraise=True`) for decorating tool `_call` methods.
  - `agentdrops.webtools.base.parse_iso_datetime(value: str | None) -> datetime | None`.
  - `agentdrops.webtools.base.parse_epoch_seconds(value: float | None) -> datetime | None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/webtools/test_base.py
from datetime import UTC, datetime
from typing import ClassVar

import httpx
import pytest

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
        return [SearchResult(tool_name=self.name, title=query, url="https://example.com", snippet=query)]


async def test_base_search_tool_subclass_returns_search_results() -> None:
    tool = _EchoSearchTool()
    results = await tool.search("market trends")
    assert results == [
        SearchResult(tool_name="echo", title="market trends", url="https://example.com", snippet="market trends")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/webtools/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.webtools.base'`

- [ ] **Step 3: Write `backend/src/agentdrops/webtools/base.py`**

```python
from abc import ABC, abstractmethod
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/webtools/test_base.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/webtools/base.py backend/tests/unit/webtools/test_base.py
git commit -m "feat(backend): add webtools base interface with retry and parsing helpers"
```

---

### Task 4: Shared test fixture + `ExaSearchTool`

**Files:**
- Create: `backend/tests/unit/webtools/conftest.py`
- Create: `backend/src/agentdrops/webtools/exa.py`
- Test: `backend/tests/unit/webtools/test_exa.py`

**Interfaces:**
- Consumes: `SearchResult`, `SearchToolError`, `BaseSearchTool`, `RETRYABLE_HTTP`, `parse_iso_datetime` from `agentdrops.webtools.base` (Task 3).
- Produces: `agentdrops.webtools.exa.ExaSearchTool(api_key: str, client: httpx.AsyncClient)` implementing `BaseSearchTool`, `name = "exa"`. Produces shared pytest fixture `http_client` (async `httpx.AsyncClient`) in `conftest.py`, reused by Tasks 5-7.

- [ ] **Step 1: Write the shared fixture**

```python
# backend/tests/unit/webtools/conftest.py
from collections.abc import AsyncIterator

import httpx
import pytest


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/webtools/test_exa.py
import httpx
import pytest
import respx

from agentdrops.webtools.base import SearchToolError
from agentdrops.webtools.exa import ExaSearchTool


@respx.mock
async def test_exa_search_returns_parsed_results(http_client: httpx.AsyncClient) -> None:
    respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "AI note-taking market overview",
                        "url": "https://example.com/article",
                        "text": "The market for AI note-taking apps is growing.",
                        "publishedDate": "2026-06-01T00:00:00Z",
                        "score": 0.87,
                    }
                ]
            },
        )
    )
    tool = ExaSearchTool(api_key="test-key", client=http_client)

    results = await tool.search("AI note-taking apps", max_results=5)

    assert len(results) == 1
    assert results[0].tool_name == "exa"
    assert results[0].title == "AI note-taking market overview"
    assert results[0].url == "https://example.com/article"
    assert results[0].snippet.startswith("The market for AI note-taking apps")
    assert results[0].score == 0.87


@respx.mock
async def test_exa_search_raises_search_tool_error_on_http_error(http_client: httpx.AsyncClient) -> None:
    respx.post("https://api.exa.ai/search").mock(return_value=httpx.Response(401, json={"error": "invalid key"}))
    tool = ExaSearchTool(api_key="bad-key", client=http_client)

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("AI note-taking apps")

    assert exc_info.value.tool_name == "exa"


@respx.mock
async def test_exa_search_retries_on_transient_5xx_then_succeeds(http_client: httpx.AsyncClient) -> None:
    route = respx.post("https://api.exa.ai/search")
    route.side_effect = [
        httpx.Response(503, json={"error": "unavailable"}),
        httpx.Response(
            200,
            json={"results": [{"title": "t", "url": "https://example.com", "text": "body"}]},
        ),
    ]
    tool = ExaSearchTool(api_key="test-key", client=http_client)

    results = await tool.search("query")

    assert len(results) == 1
    assert route.call_count == 2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/webtools/test_exa.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.webtools.exa'`

- [ ] **Step 4: Write `backend/src/agentdrops/webtools/exa.py`**

```python
from typing import Any, ClassVar

import httpx

from agentdrops.webtools.base import RETRYABLE_HTTP, BaseSearchTool, SearchResult, SearchToolError, parse_iso_datetime


class ExaSearchTool(BaseSearchTool):
    name: ClassVar[str] = "exa"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            payload = await self._call(query, max_results)
        except httpx.HTTPStatusError as exc:
            raise SearchToolError(self.name, f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.TransportError as exc:
            raise SearchToolError(self.name, f"transport error: {exc}") from exc

        results: list[SearchResult] = []
        for item in payload.get("results", []):
            results.append(
                SearchResult(
                    tool_name=self.name,
                    title=item.get("title") or item["url"],
                    url=item["url"],
                    snippet=(item.get("text") or item.get("summary") or "")[:1000],
                    published_at=parse_iso_datetime(item.get("publishedDate")),
                    score=item.get("score"),
                )
            )
        return results

    @RETRYABLE_HTTP
    async def _call(self, query: str, max_results: int) -> dict[str, Any]:
        response = await self._client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": self._api_key, "Content-Type": "application/json"},
            json={
                "query": query,
                "numResults": max_results,
                "contents": {"text": True, "summary": True},
            },
        )
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/webtools/test_exa.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add backend/tests/unit/webtools/conftest.py backend/src/agentdrops/webtools/exa.py backend/tests/unit/webtools/test_exa.py
git commit -m "feat(backend): add ExaSearchTool and shared webtools test fixture"
```

---

### Task 5: `TavilySearchTool`

**Files:**
- Create: `backend/src/agentdrops/webtools/tavily.py`
- Test: `backend/tests/unit/webtools/test_tavily.py`

**Interfaces:**
- Consumes: `SearchResult`, `SearchToolError`, `BaseSearchTool`, `RETRYABLE_HTTP` from `agentdrops.webtools.base` (Task 3); `http_client` fixture (Task 4).
- Produces: `agentdrops.webtools.tavily.TavilySearchTool(api_key: str, client: httpx.AsyncClient)` implementing `BaseSearchTool`, `name = "tavily"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/webtools/test_tavily.py
import httpx
import pytest
import respx

from agentdrops.webtools.base import SearchToolError
from agentdrops.webtools.tavily import TavilySearchTool


@respx.mock
async def test_tavily_search_returns_parsed_results(http_client: httpx.AsyncClient) -> None:
    respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "EV charging market report",
                        "url": "https://example.com/ev",
                        "content": "EV charging infrastructure is expanding rapidly.",
                        "score": 0.91,
                    }
                ]
            },
        )
    )
    tool = TavilySearchTool(api_key="tvly-test", client=http_client)

    results = await tool.search("EV charging", max_results=5)

    assert len(results) == 1
    assert results[0].tool_name == "tavily"
    assert results[0].title == "EV charging market report"
    assert results[0].url == "https://example.com/ev"
    assert results[0].snippet.startswith("EV charging infrastructure")
    assert results[0].score == 0.91


@respx.mock
async def test_tavily_search_sends_bearer_auth_header(http_client: httpx.AsyncClient) -> None:
    route = respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    tool = TavilySearchTool(api_key="tvly-test", client=http_client)

    await tool.search("EV charging")

    assert route.calls.last.request.headers["Authorization"] == "Bearer tvly-test"


@respx.mock
async def test_tavily_search_raises_search_tool_error_on_http_error(http_client: httpx.AsyncClient) -> None:
    respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    tool = TavilySearchTool(api_key="bad-key", client=http_client)

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("EV charging")

    assert exc_info.value.tool_name == "tavily"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/webtools/test_tavily.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.webtools.tavily'`

- [ ] **Step 3: Write `backend/src/agentdrops/webtools/tavily.py`**

```python
from typing import Any, ClassVar

import httpx

from agentdrops.webtools.base import RETRYABLE_HTTP, BaseSearchTool, SearchResult, SearchToolError


class TavilySearchTool(BaseSearchTool):
    name: ClassVar[str] = "tavily"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            payload = await self._call(query, max_results)
        except httpx.HTTPStatusError as exc:
            raise SearchToolError(self.name, f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.TransportError as exc:
            raise SearchToolError(self.name, f"transport error: {exc}") from exc

        results: list[SearchResult] = []
        for item in payload.get("results", []):
            results.append(
                SearchResult(
                    tool_name=self.name,
                    title=item.get("title") or item["url"],
                    url=item["url"],
                    snippet=(item.get("content") or "")[:1000],
                    published_at=None,
                    score=item.get("score"),
                )
            )
        return results

    @RETRYABLE_HTTP
    async def _call(self, query: str, max_results: int) -> dict[str, Any]:
        response = await self._client.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
            },
        )
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/webtools/test_tavily.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/webtools/tavily.py backend/tests/unit/webtools/test_tavily.py
git commit -m "feat(backend): add TavilySearchTool"
```

---

### Task 6: `NewsApiSearchTool`

**Files:**
- Create: `backend/src/agentdrops/webtools/news.py`
- Test: `backend/tests/unit/webtools/test_news.py`

**Interfaces:**
- Consumes: `SearchResult`, `SearchToolError`, `BaseSearchTool`, `RETRYABLE_HTTP`, `parse_iso_datetime` from `agentdrops.webtools.base` (Task 3); `http_client` fixture (Task 4).
- Produces: `agentdrops.webtools.news.NewsApiSearchTool(api_key: str, client: httpx.AsyncClient)` implementing `BaseSearchTool`, `name = "newsapi"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/webtools/test_news.py
import httpx
import pytest
import respx

from agentdrops.webtools.base import SearchToolError
from agentdrops.webtools.news import NewsApiSearchTool


@respx.mock
async def test_news_search_returns_parsed_results(http_client: httpx.AsyncClient) -> None:
    respx.get("https://newsapi.org/v2/everything").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "totalResults": 1,
                "articles": [
                    {
                        "title": "AI note-taking startup raises Series A",
                        "url": "https://example.com/news",
                        "description": "A new entrant raises funding.",
                        "publishedAt": "2026-06-15T09:30:00Z",
                    }
                ],
            },
        )
    )
    tool = NewsApiSearchTool(api_key="news-test", client=http_client)

    results = await tool.search("AI note-taking apps", max_results=5)

    assert len(results) == 1
    assert results[0].tool_name == "newsapi"
    assert results[0].title == "AI note-taking startup raises Series A"
    assert results[0].snippet == "A new entrant raises funding."
    assert results[0].published_at is not None


@respx.mock
async def test_news_search_sends_api_key_as_query_param(http_client: httpx.AsyncClient) -> None:
    route = respx.get("https://newsapi.org/v2/everything").mock(
        return_value=httpx.Response(200, json={"status": "ok", "totalResults": 0, "articles": []})
    )
    tool = NewsApiSearchTool(api_key="news-test", client=http_client)

    await tool.search("AI note-taking apps")

    assert route.calls.last.request.url.params["apiKey"] == "news-test"


@respx.mock
async def test_news_search_raises_search_tool_error_on_http_error(http_client: httpx.AsyncClient) -> None:
    respx.get("https://newsapi.org/v2/everything").mock(
        return_value=httpx.Response(401, json={"status": "error", "message": "bad key"})
    )
    tool = NewsApiSearchTool(api_key="bad-key", client=http_client)

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("AI note-taking apps")

    assert exc_info.value.tool_name == "newsapi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/webtools/test_news.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.webtools.news'`

- [ ] **Step 3: Write `backend/src/agentdrops/webtools/news.py`**

```python
from typing import Any, ClassVar

import httpx

from agentdrops.webtools.base import RETRYABLE_HTTP, BaseSearchTool, SearchResult, SearchToolError, parse_iso_datetime


class NewsApiSearchTool(BaseSearchTool):
    name: ClassVar[str] = "newsapi"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            payload = await self._call(query, max_results)
        except httpx.HTTPStatusError as exc:
            raise SearchToolError(self.name, f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.TransportError as exc:
            raise SearchToolError(self.name, f"transport error: {exc}") from exc

        results: list[SearchResult] = []
        for item in payload.get("articles", [])[:max_results]:
            results.append(
                SearchResult(
                    tool_name=self.name,
                    title=item.get("title") or item["url"],
                    url=item["url"],
                    snippet=(item.get("description") or item.get("content") or "")[:1000],
                    published_at=parse_iso_datetime(item.get("publishedAt")),
                    score=None,
                )
            )
        return results

    @RETRYABLE_HTTP
    async def _call(self, query: str, max_results: int) -> dict[str, Any]:
        response = await self._client.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "apiKey": self._api_key,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": min(max_results, 100),
            },
        )
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/webtools/test_news.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/webtools/news.py backend/tests/unit/webtools/test_news.py
git commit -m "feat(backend): add NewsApiSearchTool"
```

---

### Task 7: `RedditSearchTool`

**Files:**
- Create: `backend/src/agentdrops/webtools/reddit.py`
- Test: `backend/tests/unit/webtools/test_reddit.py`

**Interfaces:**
- Consumes: `SearchResult`, `SearchToolError`, `BaseSearchTool`, `RETRYABLE_HTTP`, `parse_epoch_seconds` from `agentdrops.webtools.base` (Task 3); `http_client` fixture (Task 4).
- Produces: `agentdrops.webtools.reddit.RedditSearchTool(client_id: str, client_secret: str, user_agent: str, client: httpx.AsyncClient)` implementing `BaseSearchTool`, `name = "reddit"`. Internally fetches and caches an OAuth2 client-credentials token.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/webtools/test_reddit.py
import httpx
import pytest
import respx

from agentdrops.webtools.base import SearchToolError
from agentdrops.webtools.reddit import RedditSearchTool


def _token_route() -> respx.Route:
    return respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
    )


@respx.mock
async def test_reddit_search_returns_parsed_results(http_client: httpx.AsyncClient) -> None:
    _token_route()
    respx.get("https://oauth.reddit.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "data": {
                                "title": "Anyone tried the new AI note app?",
                                "selftext": "Curious if it's worth switching.",
                                "permalink": "/r/productivity/comments/abc123/thread/",
                                "created_utc": 1751371200.0,
                                "score": 42,
                            }
                        }
                    ]
                }
            },
        )
    )
    tool = RedditSearchTool(
        client_id="cid", client_secret="csecret", user_agent="agentdrops-test/0.1", client=http_client
    )

    results = await tool.search("AI note-taking apps", max_results=5)

    assert len(results) == 1
    assert results[0].tool_name == "reddit"
    assert results[0].title == "Anyone tried the new AI note app?"
    assert results[0].url == "https://reddit.com/r/productivity/comments/abc123/thread/"
    assert results[0].snippet == "Curious if it's worth switching."
    assert results[0].score == 42
    assert results[0].published_at is not None


@respx.mock
async def test_reddit_search_reuses_cached_token_across_calls(http_client: httpx.AsyncClient) -> None:
    token_route = _token_route()
    respx.get("https://oauth.reddit.com/search").mock(
        return_value=httpx.Response(200, json={"data": {"children": []}})
    )
    tool = RedditSearchTool(
        client_id="cid", client_secret="csecret", user_agent="agentdrops-test/0.1", client=http_client
    )

    await tool.search("query one")
    await tool.search("query two")

    assert token_route.call_count == 1


@respx.mock
async def test_reddit_search_raises_search_tool_error_on_token_failure(http_client: httpx.AsyncClient) -> None:
    respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    tool = RedditSearchTool(
        client_id="bad", client_secret="bad", user_agent="agentdrops-test/0.1", client=http_client
    )

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("query")

    assert exc_info.value.tool_name == "reddit"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/webtools/test_reddit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.webtools.reddit'`

- [ ] **Step 3: Write `backend/src/agentdrops/webtools/reddit.py`**

```python
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx

from agentdrops.webtools.base import (
    RETRYABLE_HTTP,
    BaseSearchTool,
    SearchResult,
    SearchToolError,
    parse_epoch_seconds,
)


class RedditSearchTool(BaseSearchTool):
    name: ClassVar[str] = "reddit"

    def __init__(self, client_id: str, client_secret: str, user_agent: str, client: httpx.AsyncClient) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._client = client
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        token = await self._get_access_token()
        try:
            payload = await self._call(query, max_results, token)
        except httpx.HTTPStatusError as exc:
            raise SearchToolError(self.name, f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.TransportError as exc:
            raise SearchToolError(self.name, f"transport error: {exc}") from exc

        results: list[SearchResult] = []
        for child in payload.get("data", {}).get("children", [])[:max_results]:
            post = child.get("data", {})
            permalink = post.get("permalink", "")
            results.append(
                SearchResult(
                    tool_name=self.name,
                    title=post.get("title", ""),
                    url=f"https://reddit.com{permalink}" if permalink else post.get("url", ""),
                    snippet=(post.get("selftext") or "")[:1000],
                    published_at=parse_epoch_seconds(post.get("created_utc")),
                    score=post.get("score"),
                )
            )
        return results

    async def _get_access_token(self) -> str:
        if self._token and self._token_expires_at and datetime.now(UTC) < self._token_expires_at:
            return self._token

        try:
            payload = await self._fetch_token()
        except httpx.HTTPStatusError as exc:
            raise SearchToolError(self.name, f"token HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.TransportError as exc:
            raise SearchToolError(self.name, f"token transport error: {exc}") from exc

        self._token = payload["access_token"]
        self._token_expires_at = datetime.now(UTC) + timedelta(seconds=payload["expires_in"] - 60)
        return self._token

    @RETRYABLE_HTTP
    async def _fetch_token(self) -> dict[str, Any]:
        response = await self._client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self._user_agent},
        )
        response.raise_for_status()
        return response.json()

    @RETRYABLE_HTTP
    async def _call(self, query: str, max_results: int, token: str) -> dict[str, Any]:
        response = await self._client.get(
            "https://oauth.reddit.com/search",
            params={"q": query, "limit": max_results, "sort": "relevance"},
            headers={"Authorization": f"Bearer {token}", "User-Agent": self._user_agent},
        )
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/webtools/test_reddit.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/webtools/reddit.py backend/tests/unit/webtools/test_reddit.py
git commit -m "feat(backend): add RedditSearchTool with OAuth2 token caching"
```

---

### Task 8: `webtools` registry

**Files:**
- Create: `backend/src/agentdrops/webtools/registry.py`
- Modify: `backend/src/agentdrops/webtools/__init__.py`
- Test: `backend/tests/unit/test_registry.py`

**Interfaces:**
- Consumes: `Settings` from `agentdrops.config` (Task 1); `BaseSearchTool` and all four tool classes from Tasks 3-7.
- Produces: `agentdrops.webtools.registry.build_search_tools(settings: Settings, client: httpx.AsyncClient) -> list[BaseSearchTool]`. Re-exported as `agentdrops.webtools.build_search_tools`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_registry.py
import httpx

from agentdrops.config import Settings
from agentdrops.webtools import build_search_tools
from agentdrops.webtools.exa import ExaSearchTool
from agentdrops.webtools.news import NewsApiSearchTool
from agentdrops.webtools.reddit import RedditSearchTool
from agentdrops.webtools.tavily import TavilySearchTool


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key="sk-ant-test",
        exa_api_key="exa-test",
        tavily_api_key="tvly-test",
        newsapi_key="news-test",
        reddit_client_id="reddit-id",
        reddit_client_secret="reddit-secret",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentdrops",
        redis_url="redis://localhost:6379/0",
        minio_endpoint="localhost:9000",
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin",
    )


async def test_build_search_tools_returns_all_four_tools_in_order() -> None:
    async with httpx.AsyncClient() as client:
        tools = build_search_tools(_settings(), client)

    assert [type(tool) for tool in tools] == [
        ExaSearchTool,
        TavilySearchTool,
        NewsApiSearchTool,
        RedditSearchTool,
    ]
    assert [tool.name for tool in tools] == ["exa", "tavily", "newsapi", "reddit"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_registry.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_search_tools' from 'agentdrops.webtools'`

- [ ] **Step 3: Write `backend/src/agentdrops/webtools/registry.py`**

```python
import httpx

from agentdrops.config import Settings
from agentdrops.webtools.base import BaseSearchTool
from agentdrops.webtools.exa import ExaSearchTool
from agentdrops.webtools.news import NewsApiSearchTool
from agentdrops.webtools.reddit import RedditSearchTool
from agentdrops.webtools.tavily import TavilySearchTool


def build_search_tools(settings: Settings, client: httpx.AsyncClient) -> list[BaseSearchTool]:
    return [
        ExaSearchTool(api_key=settings.exa_api_key, client=client),
        TavilySearchTool(api_key=settings.tavily_api_key, client=client),
        NewsApiSearchTool(api_key=settings.newsapi_key, client=client),
        RedditSearchTool(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
            client=client,
        ),
    ]
```

- [ ] **Step 4: Update `backend/src/agentdrops/webtools/__init__.py`**

```python
from agentdrops.webtools.base import BaseSearchTool, SearchResult, SearchToolError
from agentdrops.webtools.registry import build_search_tools

__all__ = ["BaseSearchTool", "SearchResult", "SearchToolError", "build_search_tools"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_registry.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 7: Run the full test suite**

Run: `cd backend && uv run pytest -v`
Expected: PASS (all tests across Tasks 1-8)

- [ ] **Step 8: Commit**

```bash
git add backend/src/agentdrops/webtools/registry.py backend/src/agentdrops/webtools/__init__.py backend/tests/unit/test_registry.py
git commit -m "feat(backend): add webtools registry to build configured search tools from Settings"
```

---

## Definition of Done

- `cd backend && uv run ruff check .` passes with zero violations.
- `cd backend && uv run mypy src` passes with zero errors.
- `cd backend && uv run pytest -v` passes (all unit tests across config, logging, and all four webtools).
- Each of the four search tools can be constructed from `Settings` via `build_search_tools` and independently called against mocked HTTP.

## What's Next

This plan produces a tested, typed library of search tools — it does not yet run a research session end-to-end. The next plan (`docs/superpowers/plans/<next>-research-graph-and-idea-refine.md`) will consume `agentdrops.webtools.build_search_tools` to implement the LangGraph supervisor/researcher pipeline and the headless `idea_refine_generation` node, exposed via a CLI that runs a full research session and prints the final report + idea one-pager. Subsequent plans add the Postgres/MinIO/FastAPI/arq service layer and the Next.js frontend, per the design spec.
