# Resilience & Observability Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `resilience/` module (pybreaker circuit breakers wrapping tenacity retry policies for HTTP and LLM calls), migrate the four search tools built in Plan 1 onto it, add an `observability/` module (OpenTelemetry traces, metrics, and logs — replacing the structlog logging built in Plan 1 — exported via OTLP to an OTel Collector that forwards to SigNoz), and stand up the first `docker-compose.yml` for the infrastructure services that exist so far.

**Architecture:** `resilience/circuit_breaker.py` provides a named-breaker registry (`get_breaker(name)`) and an async call helper; `resilience/http_retry.py` and `resilience/llm_retry.py` each define a `tenacity` retry policy plus its retry predicate, with no dependency on `webtools` or `research` so both can consume them. Circuit breakers wrap retries (not the reverse) so a tripped breaker fails fast instead of letting `tenacity` re-attempt a known-down dependency. `observability/` configures OTel's `TracerProvider`, `MeterProvider`, and `LoggerProvider` once at process startup (`configure_observability`), all exporting via OTLP gRPC to `otel-collector`; logging keeps plain stdlib `logger.info(...)` call sites by bridging through OTel's `LoggingHandler`, with `run_id` correlation carried by a `contextvars`-backed filter (nesting-safe, replacing Plan 1's structlog-based `bind_run_id`). This is Plan 2 of the deep research market agent sequence (see `docs/superpowers/specs/2026-07-12-deepresearch-market-agent-design.md`); Plan 3 (LangGraph research graph + `prompts/v1/` + `idearefine/`) will consume `resilience/llm_retry.py` and `observability/tracing.py` directly.

**Tech Stack:** `pybreaker` (circuit breakers), `tenacity` (retries, already in use), `anthropic` (Python SDK, for LLM retry-predicate exception types), `opentelemetry-api`/`opentelemetry-sdk`/`opentelemetry-exporter-otlp-proto-grpc` (traces/metrics/logs), Docker Compose (`postgres`, `redis`, `minio`, `otel-collector`).

## Global Constraints

- Python 3.12+, `mypy --strict` must pass with zero errors — no untyped defs anywhere in `src/agentdrops`.
- `ruff check` must pass with zero violations.
- Circuit breakers wrap retries, never the reverse — a breaker trip must short-circuit the entire retry sequence for that call.
- No secrets hardcoded anywhere — all configuration flows through `agentdrops.config.Settings`.
- All I/O boundaries are Pydantic v2 models — no bare dicts crossing module boundaries.
- `resilience/` and `observability/` must not import from `webtools/`, `research/`, or `db/` — dependencies flow one way (domain modules depend on `resilience`/`observability`, never the reverse).
- `docker-compose.yml` never references a `build:` context or Dockerfile that doesn't exist yet — only fully-working services are added at any point in the plan sequence.

---

## File Structure

```
backend/
  src/agentdrops/
    resilience/
      __init__.py
      circuit_breaker.py   # get_breaker(name), call_with_breaker()
      http_retry.py          # is_retryable_http_error, HTTP_RETRY
      llm_retry.py            # is_retryable_llm_error, LLM_RETRY
    observability/
      __init__.py
      tracing.py            # configure_tracing, get_tracer, traced_span
      metrics.py             # configure_metrics, get_meter, record_tool_call
      logging.py              # configure_logging, get_logger, bind_run_id
      setup.py                 # configure_observability(settings) — wires all three
    webtools/
      base.py               # (modified) wrap_http_errors now translates pybreaker.CircuitBreakerError too
      exa.py                 # (modified) uses resilience.http_retry + circuit_breaker
      tavily.py               # (modified) same
      news.py                  # (modified) same
      reddit.py                 # (modified) same
    config.py                # (modified) + otel_service_name, otel_exporter_otlp_endpoint
    logging.py                # DELETED — replaced by observability/logging.py
  tests/
    unit/
      resilience/
        __init__.py
        test_circuit_breaker.py
        test_http_retry.py
        test_llm_retry.py
      observability/
        __init__.py
        conftest.py            # session-wide InMemorySpanExporter / InMemoryMetricReader fixtures
        test_tracing.py
        test_metrics.py
        test_logging.py
      test_config.py           # (modified) + new Settings fields
      test_logging.py          # DELETED — replaced by observability/test_logging.py
      webtools/
        test_base.py           # (modified)
        test_exa.py             # (modified)
        test_tavily.py           # (modified)
        test_news.py              # (modified)
        test_reddit.py             # (modified)
docker-compose.yml              # postgres, redis, minio, otel-collector
otel-collector-config.yaml
.env.example
```

---

### Task 1: `resilience/circuit_breaker.py`

**Files:**
- Create: `backend/src/agentdrops/resilience/__init__.py`
- Create: `backend/src/agentdrops/resilience/circuit_breaker.py`
- Modify: `backend/pyproject.toml` (add `pybreaker` dependency)
- Test: `backend/tests/unit/resilience/__init__.py`
- Test: `backend/tests/unit/resilience/test_circuit_breaker.py`

**Interfaces:**
- Produces: `agentdrops.resilience.circuit_breaker.get_breaker(name: str, *, fail_max: int = 5, reset_timeout: int = 60) -> pybreaker.CircuitBreaker` (returns the same cached instance for a given `name` on repeat calls; `fail_max`/`reset_timeout` only take effect on first creation). Produces `agentdrops.resilience.circuit_breaker.call_with_breaker(breaker: pybreaker.CircuitBreaker, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T`.

- [ ] **Step 1: Add the `pybreaker` dependency**

Edit `backend/pyproject.toml`'s `dependencies` list to add `"pybreaker>=1.2"` alongside the existing entries (keep alphabetical-ish grouping consistent with the existing list — insert after `"pydantic-settings>=2.3"` and before `"structlog>=24.1"`).

```bash
cd backend && uv sync --extra dev
```

- [ ] **Step 2: Create test package init**

```bash
mkdir -p backend/tests/unit/resilience
touch backend/tests/unit/resilience/__init__.py
```

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/unit/resilience/test_circuit_breaker.py
import pybreaker
import pytest

from agentdrops.resilience.circuit_breaker import call_with_breaker, get_breaker


def test_get_breaker_returns_same_instance_for_same_name() -> None:
    breaker_a = get_breaker("test-cb-same-name")
    breaker_b = get_breaker("test-cb-same-name")
    assert breaker_a is breaker_b


def test_get_breaker_returns_different_instances_for_different_names() -> None:
    breaker_a = get_breaker("test-cb-name-a")
    breaker_b = get_breaker("test-cb-name-b")
    assert breaker_a is not breaker_b


def test_get_breaker_applies_configured_thresholds_on_first_creation() -> None:
    breaker = get_breaker("test-cb-thresholds", fail_max=2, reset_timeout=30)
    assert breaker.fail_max == 2
    assert breaker.reset_timeout == 30


async def test_call_with_breaker_returns_result_on_success() -> None:
    breaker = get_breaker("test-cb-success")

    async def succeed() -> str:
        return "ok"

    result = await call_with_breaker(breaker, succeed)
    assert result == "ok"


async def test_call_with_breaker_propagates_the_original_exception_below_threshold() -> None:
    breaker = get_breaker("test-cb-below-threshold", fail_max=3, reset_timeout=60)

    async def fail() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await call_with_breaker(breaker, fail)


async def test_call_with_breaker_opens_after_fail_max_failures() -> None:
    breaker = get_breaker("test-cb-opens", fail_max=2, reset_timeout=60)

    async def fail() -> str:
        raise RuntimeError("boom")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await call_with_breaker(breaker, fail)

    with pytest.raises(pybreaker.CircuitBreakerError):
        await call_with_breaker(breaker, fail)


async def test_call_with_breaker_open_circuit_does_not_invoke_the_function() -> None:
    breaker = get_breaker("test-cb-short-circuits", fail_max=1, reset_timeout=60)
    call_count = 0

    async def fail() -> str:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await call_with_breaker(breaker, fail)
    assert call_count == 1

    with pytest.raises(pybreaker.CircuitBreakerError):
        await call_with_breaker(breaker, fail)
    assert call_count == 1
```

Each test uses a unique breaker name — the registry is a module-level cache that persists for the process, so reusing a name across tests would leak open-circuit state between them.

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/resilience/test_circuit_breaker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.resilience'`

- [ ] **Step 5: Write `backend/src/agentdrops/resilience/__init__.py`**

```python
```

(empty file — package marker)

- [ ] **Step 6: Write `backend/src/agentdrops/resilience/circuit_breaker.py`**

```python
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pybreaker

T = TypeVar("T")

_breakers: dict[str, pybreaker.CircuitBreaker] = {}


def get_breaker(name: str, *, fail_max: int = 5, reset_timeout: int = 60) -> pybreaker.CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = pybreaker.CircuitBreaker(
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            name=name,
        )
    return _breakers[name]


async def call_with_breaker(
    breaker: pybreaker.CircuitBreaker,
    func: Callable[..., Awaitable[T]],
    *args: Any,
    **kwargs: Any,
) -> T:
    result: T = await breaker.call_async(func, *args, **kwargs)
    return result
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/resilience/test_circuit_breaker.py -v`
Expected: PASS (6 tests)

If `breaker.call_async` doesn't exist on the installed `pybreaker` version, or behaves differently than assumed here (e.g. doesn't accept a plain coroutine function), STOP and report BLOCKED — this is a noted Key Assumption in the spec, not something to work around silently.

- [ ] **Step 8: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 9: Commit**

```bash
git add backend/pyproject.toml backend/src/agentdrops/resilience backend/tests/unit/resilience
git commit -m "feat(backend): add pybreaker-based circuit breaker registry"
```

---

### Task 2: `resilience/http_retry.py`

**Files:**
- Create: `backend/src/agentdrops/resilience/http_retry.py`
- Test: `backend/tests/unit/resilience/test_http_retry.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `agentdrops.resilience.http_retry.is_retryable_http_error(exc: BaseException) -> bool`, `agentdrops.resilience.http_retry.HTTP_RETRY` (a `tenacity.retry` decorator: 3 attempts, exponential backoff 0.5-4s, retries only on `is_retryable_http_error`, `reraise=True`). This is the same policy Plan 1 built inline in `webtools/base.py` as `RETRYABLE_HTTP`, relocated here so it has no dependency on `webtools`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/resilience/test_http_retry.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/resilience/test_http_retry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.resilience.http_retry'`

- [ ] **Step 3: Write `backend/src/agentdrops/resilience/http_retry.py`**

```python
import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


HTTP_RETRY = retry(
    retry=retry_if_exception(is_retryable_http_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    reraise=True,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/resilience/test_http_retry.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/src/agentdrops/resilience/http_retry.py backend/tests/unit/resilience/test_http_retry.py
git commit -m "feat(backend): add resilience.http_retry (moved from webtools/base.py)"
```

---

### Task 3: Migrate `webtools/base.py` onto `resilience/`

**Files:**
- Modify: `backend/src/agentdrops/webtools/base.py`
- Modify: `backend/tests/unit/webtools/test_base.py`

**Interfaces:**
- Consumes: `is_retryable_http_error`, `HTTP_RETRY` from `agentdrops.resilience.http_retry` (Task 2, no longer defined in `base.py`).
- Produces (unchanged from Plan 1, still in `agentdrops.webtools.base`): `SearchResult`, `SearchToolError`, `BaseSearchTool`, `parse_iso_datetime`, `parse_epoch_seconds`, `wrap_http_errors(tool_name: str, *, prefix: str = "") -> AbstractAsyncContextManager[None]`. `wrap_http_errors` gains a new behavior: it now also catches `pybreaker.CircuitBreakerError` and translates it into `SearchToolError(tool_name, f"{prefix}circuit open: {tool_name} unavailable")`.

- [ ] **Step 1: Write the failing test**

Replace the `is_retryable_http_error` import and its four tests in `backend/tests/unit/webtools/test_base.py` — they move to `resilience/test_http_retry.py` (already covered by Task 2) — and add a new test for the circuit-breaker translation:

```python
# backend/tests/unit/webtools/test_base.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/webtools/test_base.py -v`
Expected: FAIL — `test_wrap_http_errors_translates_circuit_breaker_error` and `test_wrap_http_errors_prefixes_circuit_breaker_message` fail because `wrap_http_errors` doesn't yet catch `pybreaker.CircuitBreakerError` (it propagates unwrapped).

- [ ] **Step 3: Modify `backend/src/agentdrops/webtools/base.py`**

Replace its full contents with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/webtools/test_base.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Run the full suite to check for breakage in the other webtools (expected — fixed in Tasks 4-5)**

Run: `cd backend && uv run pytest tests/unit/webtools -v`
Expected: `test_base.py` passes; `test_exa.py`, `test_tavily.py`, `test_news.py`, `test_reddit.py` FAIL with `ImportError: cannot import name 'is_retryable_http_error' from 'agentdrops.webtools.base'` (or similar) — this is expected at this point in the plan and is fixed by Tasks 4 and 5. Do not attempt to fix the other tool files in this task.

- [ ] **Step 6: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: `webtools/base.py` itself is clean; the other four tool files will still reference the old `agentdrops.webtools.base.RETRYABLE_HTTP` import and fail — that's expected and fixed in Tasks 4-5.

- [ ] **Step 7: Commit**

```bash
git add backend/src/agentdrops/webtools/base.py backend/tests/unit/webtools/test_base.py
git commit -m "refactor(backend): migrate webtools/base.py retry logic to resilience/, wrap circuit-breaker errors"
```

---

### Task 4: Migrate `ExaSearchTool` and `TavilySearchTool` onto `resilience/`

**Files:**
- Modify: `backend/src/agentdrops/webtools/exa.py`
- Modify: `backend/src/agentdrops/webtools/tavily.py`
- Modify: `backend/tests/unit/webtools/test_exa.py`
- Modify: `backend/tests/unit/webtools/test_tavily.py`

**Interfaces:**
- Consumes: `HTTP_RETRY` from `agentdrops.resilience.http_retry` (Task 2); `get_breaker`, `call_with_breaker` from `agentdrops.resilience.circuit_breaker` (Task 1); `wrap_http_errors` from `agentdrops.webtools.base` (Task 3, now circuit-breaker-aware).
- Produces: no new public interface — `ExaSearchTool`/`TavilySearchTool`'s public `search()` signature and behavior are unchanged; internally, each now routes its `_call` through `call_with_breaker(get_breaker(self.name), self._call, ...)`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/webtools/test_exa.py
import httpx
import pybreaker
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


@respx.mock
async def test_exa_search_raises_search_tool_error_on_malformed_response(http_client: httpx.AsyncClient) -> None:
    respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(200, json={"results": [{"title": "t"}]})
    )
    tool = ExaSearchTool(api_key="test-key", client=http_client)

    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("query")

    assert exc_info.value.tool_name == "exa"


@respx.mock
async def test_exa_search_raises_search_tool_error_when_circuit_open(http_client: httpx.AsyncClient) -> None:
    respx.post("https://api.exa.ai/search").mock(return_value=httpx.Response(500, json={"error": "down"}))
    tool = ExaSearchTool(api_key="test-key", client=http_client, breaker_fail_max=1)

    with pytest.raises(SearchToolError):
        await tool.search("first call trips the breaker")

    route = respx.post("https://api.exa.ai/search")
    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("second call should short-circuit")

    assert "circuit open" in str(exc_info.value)
    assert route.call_count == 0
```

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


@respx.mock
async def test_tavily_search_raises_search_tool_error_when_circuit_open(http_client: httpx.AsyncClient) -> None:
    respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(500, json={"error": "down"}))
    tool = TavilySearchTool(api_key="tvly-test", client=http_client, breaker_fail_max=1)

    with pytest.raises(SearchToolError):
        await tool.search("first call trips the breaker")

    route = respx.post("https://api.tavily.com/search")
    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("second call should short-circuit")

    assert "circuit open" in str(exc_info.value)
    assert route.call_count == 0
```

Note: both tools' `__init__` gains an optional `breaker_fail_max: int = 5` parameter (see Step 3) purely so tests can trip the breaker in one call instead of five — production callers (the registry, in a later task) don't need to pass it and get the default.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/webtools/test_exa.py tests/unit/webtools/test_tavily.py -v`
Expected: FAIL — `ImportError` (old `RETRYABLE_HTTP` import from `webtools.base` no longer exists) and/or the new circuit-open tests fail since breaker wiring doesn't exist yet.

- [ ] **Step 3: Modify `backend/src/agentdrops/webtools/exa.py`**

```python
from typing import Any, ClassVar, cast

import httpx

from agentdrops.resilience.circuit_breaker import call_with_breaker, get_breaker
from agentdrops.resilience.http_retry import HTTP_RETRY
from agentdrops.webtools.base import BaseSearchTool, SearchResult, parse_iso_datetime, wrap_http_errors


class ExaSearchTool(BaseSearchTool):
    name: ClassVar[str] = "exa"

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient,
        *,
        breaker_fail_max: int = 5,
        breaker_reset_timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._breaker = get_breaker(self.name, fail_max=breaker_fail_max, reset_timeout=breaker_reset_timeout)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with wrap_http_errors(self.name):
            payload = await call_with_breaker(self._breaker, self._call, query, max_results)
            results: list[SearchResult] = []
            for item in payload.get("results", [])[:max_results]:
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

    @HTTP_RETRY
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
        return cast(dict[str, Any], response.json())
```

- [ ] **Step 4: Modify `backend/src/agentdrops/webtools/tavily.py`**

```python
from typing import Any, ClassVar, cast

import httpx

from agentdrops.resilience.circuit_breaker import call_with_breaker, get_breaker
from agentdrops.resilience.http_retry import HTTP_RETRY
from agentdrops.webtools.base import BaseSearchTool, SearchResult, wrap_http_errors


class TavilySearchTool(BaseSearchTool):
    name: ClassVar[str] = "tavily"

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient,
        *,
        breaker_fail_max: int = 5,
        breaker_reset_timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._breaker = get_breaker(self.name, fail_max=breaker_fail_max, reset_timeout=breaker_reset_timeout)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with wrap_http_errors(self.name):
            payload = await call_with_breaker(self._breaker, self._call, query, max_results)
            results: list[SearchResult] = []
            for item in payload.get("results", [])[:max_results]:
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

    @HTTP_RETRY
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
        return cast(dict[str, Any], response.json())
```

Note both `__init__`s call `get_breaker(self.name, ...)` — since `get_breaker` caches by name and `fail_max`/`reset_timeout` only apply on first creation for that name, and tests in Task 1 and this task use distinct breaker names (`"test-cb-*"` vs. `"exa"`/`"tavily"`) there's no cross-test collision. Within `test_exa.py` itself, the `breaker_fail_max=1` test runs against the shared `"exa"`-named breaker used by the OTHER tests in the same file — order matters. To keep tests independent, the circuit-open test must use a distinct tool-name-like breaker to avoid tripping the breaker other tests in the file rely on being closed. Handle this by having `ExaSearchTool.__init__` accept the breaker name lookup as `get_breaker(self.name, ...)` as shown, and in the circuit-open test's dispatch note below, flag this ordering risk to the implementer explicitly so they either namespace the test's breaker or run it in its own file-scoped fixture — do not leave this unresolved.

- [ ] **Step 5: Resolve the breaker test-isolation risk**

Before running the suite, address the ordering issue named in Step 4: the simplest fix is a `conftest.py` fixture that resets the module-level `_breakers` dict in `agentdrops.resilience.circuit_breaker` between tests, so every test starts with fresh breaker state regardless of order or shared tool name. Add this to `backend/tests/unit/webtools/conftest.py` (alongside the existing `http_client` fixture):

```python
# backend/tests/unit/webtools/conftest.py
from collections.abc import AsyncIterator

import httpx
import pytest

from agentdrops.resilience.circuit_breaker import _breakers


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture(autouse=True)
def _reset_circuit_breakers() -> None:
    _breakers.clear()
```

This also means the `test-cb-*` named tests in `backend/tests/unit/resilience/test_circuit_breaker.py` (Task 1) no longer strictly need unique names for isolation from OTHER test files, but keep them unique regardless — it's clearer and doesn't rely on fixture ordering across directories.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/webtools/test_exa.py tests/unit/webtools/test_tavily.py -v`
Expected: PASS (5 tests in test_exa.py, 4 in test_tavily.py)

- [ ] **Step 7: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: `exa.py`, `tavily.py`, and their tests are clean. `news.py`/`reddit.py` still fail — expected, fixed in Task 5.

- [ ] **Step 8: Commit**

```bash
git add backend/src/agentdrops/webtools/exa.py backend/src/agentdrops/webtools/tavily.py backend/tests/unit/webtools/test_exa.py backend/tests/unit/webtools/test_tavily.py backend/tests/unit/webtools/conftest.py
git commit -m "refactor(backend): migrate ExaSearchTool and TavilySearchTool onto resilience/ (retry + circuit breaker)"
```

---

### Task 5: Migrate `NewsApiSearchTool` and `RedditSearchTool` onto `resilience/`

**Files:**
- Modify: `backend/src/agentdrops/webtools/news.py`
- Modify: `backend/src/agentdrops/webtools/reddit.py`
- Modify: `backend/tests/unit/webtools/test_news.py`
- Modify: `backend/tests/unit/webtools/test_reddit.py`

**Interfaces:**
- Consumes: same as Task 4 (`HTTP_RETRY`, `get_breaker`, `call_with_breaker`, `wrap_http_errors`), plus the `_reset_circuit_breakers` autouse fixture from Task 4's `conftest.py`.
- Produces: no new public interface — behavior unchanged; `RedditSearchTool` uses ONE breaker (named `"reddit"`) for both its token fetch and its search call, since both hit the same underlying dependency.

- [ ] **Step 1: Write the failing tests**

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


@respx.mock
async def test_news_search_raises_search_tool_error_when_circuit_open(http_client: httpx.AsyncClient) -> None:
    respx.get("https://newsapi.org/v2/everything").mock(return_value=httpx.Response(500, json={"status": "error"}))
    tool = NewsApiSearchTool(api_key="news-test", client=http_client, breaker_fail_max=1)

    with pytest.raises(SearchToolError):
        await tool.search("first call trips the breaker")

    route = respx.get("https://newsapi.org/v2/everything")
    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("second call should short-circuit")

    assert "circuit open" in str(exc_info.value)
    assert route.call_count == 0
```

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


@respx.mock
async def test_reddit_search_raises_search_tool_error_when_circuit_open(http_client: httpx.AsyncClient) -> None:
    respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(500, json={"error": "down"})
    )
    tool = RedditSearchTool(
        client_id="cid",
        client_secret="csecret",
        user_agent="agentdrops-test/0.1",
        client=http_client,
        breaker_fail_max=1,
    )

    with pytest.raises(SearchToolError):
        await tool.search("first call trips the breaker")

    token_route = respx.post("https://www.reddit.com/api/v1/access_token")
    with pytest.raises(SearchToolError) as exc_info:
        await tool.search("second call should short-circuit")

    assert "circuit open" in str(exc_info.value)
    assert token_route.call_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/webtools/test_news.py tests/unit/webtools/test_reddit.py -v`
Expected: FAIL — same `ImportError`/missing-breaker-wiring pattern as Task 4.

- [ ] **Step 3: Modify `backend/src/agentdrops/webtools/news.py`**

```python
from typing import Any, ClassVar, cast

import httpx

from agentdrops.resilience.circuit_breaker import call_with_breaker, get_breaker
from agentdrops.resilience.http_retry import HTTP_RETRY
from agentdrops.webtools.base import BaseSearchTool, SearchResult, parse_iso_datetime, wrap_http_errors


class NewsApiSearchTool(BaseSearchTool):
    name: ClassVar[str] = "newsapi"

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient,
        *,
        breaker_fail_max: int = 5,
        breaker_reset_timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._breaker = get_breaker(self.name, fail_max=breaker_fail_max, reset_timeout=breaker_reset_timeout)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with wrap_http_errors(self.name):
            payload = await call_with_breaker(self._breaker, self._call, query, max_results)
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

    @HTTP_RETRY
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
        return cast(dict[str, Any], response.json())
```

- [ ] **Step 4: Modify `backend/src/agentdrops/webtools/reddit.py`**

```python
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

import httpx

from agentdrops.resilience.circuit_breaker import call_with_breaker, get_breaker
from agentdrops.resilience.http_retry import HTTP_RETRY
from agentdrops.webtools.base import BaseSearchTool, SearchResult, parse_epoch_seconds, wrap_http_errors


class RedditSearchTool(BaseSearchTool):
    name: ClassVar[str] = "reddit"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        client: httpx.AsyncClient,
        *,
        breaker_fail_max: int = 5,
        breaker_reset_timeout: int = 60,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._client = client
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._breaker = get_breaker(self.name, fail_max=breaker_fail_max, reset_timeout=breaker_reset_timeout)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        token = await self._get_access_token()
        async with wrap_http_errors(self.name):
            payload = await call_with_breaker(self._breaker, self._call, query, max_results, token)
            results: list[SearchResult] = []
            for child in payload.get("data", {}).get("children", [])[:max_results]:
                post = child.get("data", {})
                permalink = post.get("permalink", "")
                url = f"https://reddit.com{permalink}" if permalink else post.get("url", "")
                results.append(
                    SearchResult(
                        tool_name=self.name,
                        title=post.get("title") or url,
                        url=url,
                        snippet=(post.get("selftext") or "")[:1000],
                        published_at=parse_epoch_seconds(post.get("created_utc")),
                        score=post.get("score"),
                    )
                )
        return results

    async def _get_access_token(self) -> str:
        if self._token and self._token_expires_at and datetime.now(UTC) < self._token_expires_at:
            return self._token

        async with wrap_http_errors(self.name, prefix="token "):
            payload = await call_with_breaker(self._breaker, self._fetch_token)
            self._token = payload["access_token"]
            self._token_expires_at = datetime.now(UTC) + timedelta(seconds=payload["expires_in"] - 60)
        return self._token

    @HTTP_RETRY
    async def _fetch_token(self) -> dict[str, Any]:
        response = await self._client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self._user_agent},
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    @HTTP_RETRY
    async def _call(self, query: str, max_results: int, token: str) -> dict[str, Any]:
        response = await self._client.get(
            "https://oauth.reddit.com/search",
            params={"q": query, "limit": max_results, "sort": "relevance"},
            headers={"Authorization": f"Bearer {token}", "User-Agent": self._user_agent},
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())
```

Note this task also folds in the two Plan-1-review findings that were previously fixed inline (title-fallback-to-`url` consistency, 500-char error truncation via `wrap_http_errors`, `KeyError`→`SearchToolError` wrapping) — they're preserved here since this is a migration, not a rewrite; verify the diff doesn't regress them.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/webtools/test_news.py tests/unit/webtools/test_reddit.py -v`
Expected: PASS (4 tests in test_news.py, 5 in test_reddit.py)

- [ ] **Step 6: Run the full webtools suite**

Run: `cd backend && uv run pytest tests/unit/webtools tests/unit/resilience -v`
Expected: PASS (all tests across `webtools/` and `resilience/`)

- [ ] **Step 7: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 8: Update `backend/src/agentdrops/webtools/registry.py` if needed**

Read the current file. If `build_search_tools` still constructs each tool with only the original keyword arguments (`api_key`/`client_id`+`client_secret`+`user_agent`, `client`), no change is needed — the new `breaker_fail_max`/`breaker_reset_timeout` parameters are keyword-only with defaults, so existing call sites remain valid. Confirm this by re-running:

Run: `cd backend && uv run pytest tests/unit/test_registry.py -v`
Expected: PASS (1 test, unchanged)

- [ ] **Step 9: Commit**

```bash
git add backend/src/agentdrops/webtools/news.py backend/src/agentdrops/webtools/reddit.py backend/tests/unit/webtools/test_news.py backend/tests/unit/webtools/test_reddit.py
git commit -m "refactor(backend): migrate NewsApiSearchTool and RedditSearchTool onto resilience/ (retry + circuit breaker)"
```

---

### Task 6: `resilience/llm_retry.py`

**Files:**
- Create: `backend/src/agentdrops/resilience/llm_retry.py`
- Modify: `backend/pyproject.toml` (add `anthropic` dependency)
- Test: `backend/tests/unit/resilience/test_llm_retry.py`

**Interfaces:**
- Consumes: nothing from other Tasks in this plan.
- Produces: `agentdrops.resilience.llm_retry.is_retryable_llm_error(exc: BaseException) -> bool`, `agentdrops.resilience.llm_retry.LLM_RETRY` (a `tenacity.retry` decorator: 5 attempts, exponential backoff 1-20s, retries only on `is_retryable_llm_error`, `reraise=True`). Not consumed by anything yet in this plan — Plan 3's research graph will decorate its Anthropic API call sites with `@LLM_RETRY`.

- [ ] **Step 1: Add the `anthropic` dependency**

Edit `backend/pyproject.toml`'s `dependencies` list to add `"anthropic>=0.40"`.

```bash
cd backend && uv sync --extra dev
```

- [ ] **Step 2: Verify the `anthropic` SDK's exception constructor signatures before writing the test**

The exception shapes below are the standard `anthropic`-SDK pattern (`APIStatusError` subclasses take `(message, *, response: httpx.Response, body: object)`; `APIConnectionError` takes `(*, message: str = ..., request: httpx.Request)`), but SDK versions do shift these details. Before writing the test, confirm the actual signatures in the installed version:

```bash
cd backend && uv run python -c "
import inspect, anthropic
print(inspect.signature(anthropic.APIStatusError.__init__))
print(inspect.signature(anthropic.APIConnectionError.__init__))
print(anthropic.RateLimitError.__mro__)
print(anthropic.InternalServerError.__mro__)
print(anthropic.BadRequestError.__mro__)
"
```

If the signatures differ from what Step 3's test below assumes, adapt the test's helper function to match what you observed — do not guess, use the actual output. If `anthropic.RateLimitError`, `anthropic.InternalServerError`, `anthropic.BadRequestError`, or `anthropic.APIConnectionError` don't exist under those exact names in the installed version, STOP and report NEEDS_CONTEXT with what you found instead.

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/unit/resilience/test_llm_retry.py
import anthropic
import httpx

from agentdrops.resilience.llm_retry import is_retryable_llm_error


def _status_error(cls: type[anthropic.APIStatusError], status_code: int) -> anthropic.APIStatusError:
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
```

If Step 2 revealed different constructor signatures, adjust `_status_error` and the `APIConnectionError` call accordingly before proceeding — keep the test names and assertions the same, only the construction helper changes.

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/resilience/test_llm_retry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.resilience.llm_retry'`

- [ ] **Step 5: Write `backend/src/agentdrops/resilience/llm_retry.py`**

```python
import anthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def is_retryable_llm_error(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.RateLimitError | anthropic.InternalServerError | anthropic.APIConnectionError):
        return True
    return False


LLM_RETRY = retry(
    retry=retry_if_exception(is_retryable_llm_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/resilience/test_llm_retry.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/src/agentdrops/resilience/llm_retry.py backend/tests/unit/resilience/test_llm_retry.py
git commit -m "feat(backend): add resilience.llm_retry for Anthropic API calls"
```

---

### Task 7: `observability/tracing.py`

**Files:**
- Create: `backend/src/agentdrops/observability/__init__.py`
- Create: `backend/src/agentdrops/observability/tracing.py`
- Create: `backend/tests/unit/observability/__init__.py`
- Create: `backend/tests/unit/observability/conftest.py`
- Modify: `backend/pyproject.toml` (add OpenTelemetry dependencies)
- Test: `backend/tests/unit/observability/test_tracing.py`

**Interfaces:**
- Consumes: nothing from other Tasks in this plan.
- Produces: `agentdrops.observability.tracing.configure_tracing(service_name: str, otlp_endpoint: str) -> TracerProvider` (also sets it as the global provider), `agentdrops.observability.tracing.get_tracer(name: str) -> Tracer`, `agentdrops.observability.tracing.traced_span(name: str, **attributes: str | int | float | bool) -> AbstractContextManager[Span]`. Also produces the `backend/tests/unit/observability/conftest.py` fixtures `span_exporter` (an `InMemorySpanExporter`, cleared before each test) — consumed by this task's tests only; metrics/logging tests in Tasks 8-9 add their own fixtures to the same file.

- [ ] **Step 1: Add OpenTelemetry dependencies**

Edit `backend/pyproject.toml`'s `dependencies` list to add:

```toml
    "opentelemetry-api>=1.27",
    "opentelemetry-sdk>=1.27",
    "opentelemetry-exporter-otlp-proto-grpc>=1.27",
```

```bash
cd backend && uv sync --extra dev
```

- [ ] **Step 2: Create test package init and shared conftest**

```bash
mkdir -p backend/tests/unit/observability
touch backend/tests/unit/observability/__init__.py
```

```python
# backend/tests/unit/observability/conftest.py
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_span_exporter = InMemorySpanExporter()
_tracer_provider = TracerProvider()
_tracer_provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
trace.set_tracer_provider(_tracer_provider)


@pytest.fixture
def span_exporter() -> Iterator[InMemorySpanExporter]:
    _span_exporter.clear()
    yield _span_exporter
```

This module-level setup runs once, the first time pytest collects this conftest, and calls `trace.set_tracer_provider` exactly once for the whole test session — OpenTelemetry's API only honors the first call to `set_tracer_provider` per process (later calls are logged and ignored), so this must be the only place in the test suite that calls it.

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/unit/observability/test_tracing.py
from opentelemetry.sdk.resources import SERVICE_NAME
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agentdrops.observability.tracing import configure_tracing, get_tracer, traced_span


def test_traced_span_records_a_finished_span_with_attributes(span_exporter: InMemorySpanExporter) -> None:
    with traced_span("supervisor_node", run_id="run-123", iteration=1):
        pass

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "supervisor_node"
    assert spans[0].attributes is not None
    assert spans[0].attributes["run_id"] == "run-123"
    assert spans[0].attributes["iteration"] == 1


def test_traced_span_records_exception_and_still_ends_span(span_exporter: InMemorySpanExporter) -> None:
    try:
        with traced_span("failing_node"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "failing_node"


def test_get_tracer_returns_a_tracer() -> None:
    tracer = get_tracer("agentdrops.test")
    assert tracer is not None


def test_configure_tracing_returns_provider_with_service_name_resource() -> None:
    provider = configure_tracing(service_name="agentdrops-test", otlp_endpoint="http://localhost:4317")
    assert provider.resource.attributes[SERVICE_NAME] == "agentdrops-test"
```

`test_configure_tracing_returns_provider_with_service_name_resource` constructs its own `TracerProvider` and returns it WITHOUT relying on the global (it still calls `trace.set_tracer_provider` internally as a side effect for production use, but since the conftest already set the global first, that inner call is a no-op per OTel's set-once behavior — this test only asserts on the returned object, not the global, so that's fine).

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/observability/test_tracing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.observability'`

- [ ] **Step 5: Write `backend/src/agentdrops/observability/__init__.py`**

```python
```

(empty file — package marker)

- [ ] **Step 6: Write `backend/src/agentdrops/observability/tracing.py`**

```python
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Tracer


def configure_tracing(service_name: str, otlp_endpoint: str) -> TracerProvider:
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def get_tracer(name: str) -> Tracer:
    return trace.get_tracer(name)


@contextmanager
def traced_span(name: str, **attributes: str | int | float | bool) -> Iterator[Span]:
    tracer = get_tracer("agentdrops")
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        yield span
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/observability/test_tracing.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 9: Commit**

```bash
git add backend/pyproject.toml backend/src/agentdrops/observability/__init__.py backend/src/agentdrops/observability/tracing.py backend/tests/unit/observability
git commit -m "feat(backend): add observability.tracing (OpenTelemetry TracerProvider + traced_span)"
```

---

### Task 8: `observability/metrics.py`

**Files:**
- Create: `backend/src/agentdrops/observability/metrics.py`
- Modify: `backend/tests/unit/observability/conftest.py` (add metric-reader fixture)
- Test: `backend/tests/unit/observability/test_metrics.py`

**Interfaces:**
- Consumes: nothing from other Tasks (independent of `tracing.py`).
- Produces: `agentdrops.observability.metrics.configure_metrics(service_name: str, otlp_endpoint: str) -> MeterProvider`, `agentdrops.observability.metrics.get_meter(name: str) -> Meter`, `agentdrops.observability.metrics.record_tool_call(tool_name: str, duration_seconds: float, *, success: bool) -> None` (records to a histogram named `agentdrops.tool_call.duration`, attributes `{tool_name, success}`).

- [ ] **Step 1: Add the metric-reader fixture**

Append to `backend/tests/unit/observability/conftest.py`:

```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

_metric_reader = InMemoryMetricReader()
_meter_provider = MeterProvider(metric_readers=[_metric_reader])
metrics.set_meter_provider(_meter_provider)


@pytest.fixture
def metric_reader() -> InMemoryMetricReader:
    return _metric_reader
```

(Add the new imports to the top of the file alongside the existing `trace`-related ones; `pytest` is already imported.)

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/observability/test_metrics.py
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME

from agentdrops.observability.metrics import configure_metrics, get_meter, record_tool_call


def test_record_tool_call_emits_a_histogram_data_point(metric_reader: InMemoryMetricReader) -> None:
    record_tool_call("exa", 0.42, success=True)

    data = metric_reader.get_metrics_data()
    assert data is not None
    metric_names = [
        metric.name
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    ]
    assert "agentdrops.tool_call.duration" in metric_names


def test_get_meter_returns_a_meter() -> None:
    meter = get_meter("agentdrops.test")
    assert meter is not None


def test_configure_metrics_returns_provider_with_service_name_resource() -> None:
    provider = configure_metrics(service_name="agentdrops-test", otlp_endpoint="http://localhost:4317")
    assert provider._sdk_config.resource.attributes[SERVICE_NAME] == "agentdrops-test"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/observability/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.observability.metrics'`

- [ ] **Step 4: Write `backend/src/agentdrops/observability/metrics.py`**

```python
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource


def configure_metrics(service_name: str, otlp_endpoint: str) -> MeterProvider:
    resource = Resource.create({SERVICE_NAME: service_name})
    exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
    reader = PeriodicExportingMetricReader(exporter)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


def get_meter(name: str) -> Meter:
    return metrics.get_meter(name)


_tool_call_duration: Histogram | None = None


def record_tool_call(tool_name: str, duration_seconds: float, *, success: bool) -> None:
    global _tool_call_duration
    if _tool_call_duration is None:
        _tool_call_duration = get_meter("agentdrops").create_histogram(
            name="agentdrops.tool_call.duration",
            unit="s",
            description="Duration of an external tool call (search tool or LLM call).",
        )
    _tool_call_duration.record(duration_seconds, attributes={"tool_name": tool_name, "success": success})
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/observability/test_metrics.py -v`
Expected: PASS (3 tests)

If `MeterProvider._sdk_config` doesn't exist on the installed SDK version (private attribute access is fragile across versions), simplify `test_configure_metrics_returns_provider_with_service_name_resource` to only assert `provider is not None` and drop the resource-attribute check — note this as a concern in your report rather than fighting SDK internals.

- [ ] **Step 6: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add backend/src/agentdrops/observability/metrics.py backend/tests/unit/observability/conftest.py backend/tests/unit/observability/test_metrics.py
git commit -m "feat(backend): add observability.metrics (OpenTelemetry MeterProvider + tool-call duration histogram)"
```

---

### Task 9: `observability/logging.py` (replaces Plan 1's `agentdrops/logging.py`)

**Files:**
- Create: `backend/src/agentdrops/observability/logging.py`
- Delete: `backend/src/agentdrops/logging.py`
- Delete: `backend/tests/unit/test_logging.py`
- Modify: `backend/pyproject.toml` (remove `structlog` dependency, add OTel Logs exporter)
- Test: `backend/tests/unit/observability/test_logging.py`

**Interfaces:**
- Consumes: nothing from other Tasks in this plan.
- Produces: `agentdrops.observability.logging.configure_logging(service_name: str, otlp_endpoint: str, level: str = "INFO") -> LoggerProvider`, `agentdrops.observability.logging.get_logger(name: str) -> logging.Logger` (a plain stdlib logger — callers use `logger.info(...)` etc.), `agentdrops.observability.logging.bind_run_id(run_id: str) -> AbstractContextManager[None]` (nesting-safe via `contextvars.Token`, unlike Plan 1's structlog-based version).

- [ ] **Step 1: Update dependencies**

Edit `backend/pyproject.toml`: remove `"structlog>=24.1"` from `dependencies`, add `"opentelemetry-exporter-otlp-proto-grpc>=1.27"` if not already present from Task 7 (it is — no duplicate needed), and no new package is required for `opentelemetry.sdk._logs` — it ships inside `opentelemetry-sdk` (already added in Task 7).

```bash
cd backend && uv sync --extra dev
```

- [ ] **Step 2: Delete Plan 1's structlog-based logging module and its test**

```bash
git rm backend/src/agentdrops/logging.py backend/tests/unit/test_logging.py
```

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/unit/observability/test_logging.py
import logging

from opentelemetry.sdk.resources import SERVICE_NAME

from agentdrops.observability.logging import (
    _RunIdFilter,
    _run_id_var,
    bind_run_id,
    configure_logging,
    get_logger,
)


def test_run_id_filter_stamps_record_with_bound_run_id() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)
    with bind_run_id("run-123"):
        _RunIdFilter().filter(record)
    assert record.run_id == "run-123"  # type: ignore[attr-defined]


def test_run_id_filter_stamps_none_when_unbound() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)
    _RunIdFilter().filter(record)
    assert record.run_id is None  # type: ignore[attr-defined]


def test_bind_run_id_resets_after_context_exits() -> None:
    with bind_run_id("run-123"):
        assert _run_id_var.get() == "run-123"
    assert _run_id_var.get() is None


def test_bind_run_id_restores_outer_value_when_nested() -> None:
    with bind_run_id("outer"):
        with bind_run_id("inner"):
            assert _run_id_var.get() == "inner"
        assert _run_id_var.get() == "outer"
    assert _run_id_var.get() is None


def test_get_logger_returns_a_stdlib_logger() -> None:
    logger = get_logger("agentdrops.test")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "agentdrops.test"


def test_configure_logging_returns_provider_with_service_name_resource() -> None:
    provider = configure_logging(service_name="agentdrops-test", otlp_endpoint="http://localhost:4317")
    assert provider.resource.attributes[SERVICE_NAME] == "agentdrops-test"
```

`record.run_id` is a dynamically-added attribute (that's the whole point of a logging `Filter`), so `mypy --strict` needs the `# type: ignore[attr-defined]` on the two lines that read it back in the test — this is expected and not a workaround for a real error.

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/observability/test_logging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.observability.logging'`

- [ ] **Step 5: Write `backend/src/agentdrops/observability/logging.py`**

```python
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

_run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id_var.get()  # type: ignore[attr-defined]
        return True


def configure_logging(service_name: str, otlp_endpoint: str, level: str = "INFO") -> LoggerProvider:
    numeric_level = _LEVEL_MAP.get(level.upper(), logging.INFO)
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = LoggerProvider(resource=resource)
    exporter = OTLPLogExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    handler = LoggingHandler(level=numeric_level, logger_provider=provider)
    handler.addFilter(_RunIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.addHandler(handler)
    return provider


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def bind_run_id(run_id: str) -> Iterator[None]:
    token = _run_id_var.set(run_id)
    try:
        yield
    finally:
        _run_id_var.reset(token)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/observability/test_logging.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Run the full suite**

Run: `cd backend && uv run pytest -v`
Expected: PASS — confirm the deleted `test_logging.py` (Plan 1's) is gone from the collected tests and nothing else references `agentdrops.logging` (search first: `grep -rn "agentdrops.logging" backend/src backend/tests` should return nothing except `agentdrops.observability.logging`).

- [ ] **Step 8: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 9: Commit**

```bash
git add backend/pyproject.toml backend/src/agentdrops/observability/logging.py backend/tests/unit/observability/test_logging.py
git add backend/src/agentdrops/logging.py backend/tests/unit/test_logging.py
git commit -m "feat(backend): replace structlog with observability.logging (OTel LoggingHandler bridge)"
```

(The second `git add` stages the deletions from Step 2 — `git add` on a path already removed from the working tree stages the removal.)

---

### Task 10: `observability/setup.py` — single entrypoint + `Settings` additions

**Files:**
- Create: `backend/src/agentdrops/observability/setup.py`
- Modify: `backend/src/agentdrops/config.py`
- Modify: `backend/tests/unit/test_config.py`
- Test: `backend/tests/unit/observability/test_setup.py`

**Interfaces:**
- Consumes: `configure_tracing` (Task 7), `configure_metrics` (Task 8), `configure_logging` (Task 9); `Settings` from `agentdrops.config`.
- Produces: `agentdrops.observability.setup.configure_observability(settings: Settings) -> None` — calls all three `configure_*` functions using `settings.otel_service_name` and `settings.otel_exporter_otlp_endpoint`. Adds two new fields to `Settings`: `otel_service_name: str = "agentdrops"`, `otel_exporter_otlp_endpoint: str = "http://localhost:4317"`.

- [ ] **Step 1: Write the failing test for the `Settings` additions**

Add to `backend/tests/unit/test_config.py` (both existing test functions already set every other required field — add assertions for the two new fields with their defaults, since they're optional with defaults rather than required):

```python
def test_settings_otel_fields_have_sensible_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert settings.otel_service_name == "agentdrops"
    assert settings.otel_exporter_otlp_endpoint == "http://localhost:4317"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_config.py -v`
Expected: FAIL — `AttributeError` or `ValidationError`, `Settings` has no `otel_service_name`/`otel_exporter_otlp_endpoint` fields yet.

- [ ] **Step 3: Modify `backend/src/agentdrops/config.py`**

Read the current file first. Add these two fields to the `Settings` class, after the existing `minio_secret_key: str` field and before `log_level: str = "INFO"`:

```python
    otel_service_name: str = "agentdrops"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write the failing test for `configure_observability`**

```python
# backend/tests/unit/observability/test_setup.py
from agentdrops.config import Settings
from agentdrops.observability.setup import configure_observability


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


def test_configure_observability_does_not_raise() -> None:
    configure_observability(_settings())
```

This is deliberately a smoke test, not a behavioral one — `configure_observability` wires three OTel providers that were already unit-tested individually in Tasks 7-9 (and whose `set_tracer_provider`/`set_meter_provider` calls are no-ops here anyway, since the session's `conftest.py` already set both globals first). The only new risk this task introduces is the three `configure_*` calls being wired together with the right `Settings` fields without raising — that's what this test protects.

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/observability/test_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentdrops.observability.setup'`

- [ ] **Step 7: Write `backend/src/agentdrops/observability/setup.py`**

```python
from agentdrops.config import Settings
from agentdrops.observability.logging import configure_logging
from agentdrops.observability.metrics import configure_metrics
from agentdrops.observability.tracing import configure_tracing


def configure_observability(settings: Settings) -> None:
    configure_tracing(service_name=settings.otel_service_name, otlp_endpoint=settings.otel_exporter_otlp_endpoint)
    configure_metrics(service_name=settings.otel_service_name, otlp_endpoint=settings.otel_exporter_otlp_endpoint)
    configure_logging(
        service_name=settings.otel_service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        level=settings.log_level,
    )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/observability/test_setup.py -v`
Expected: PASS (1 test)

- [ ] **Step 9: Run the full suite**

Run: `cd backend && uv run pytest -v`
Expected: PASS — all tests across the whole `backend/` tree.

- [ ] **Step 10: Lint and type-check**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: no errors

- [ ] **Step 11: Commit**

```bash
git add backend/src/agentdrops/config.py backend/src/agentdrops/observability/setup.py backend/tests/unit/test_config.py backend/tests/unit/observability/test_setup.py
git commit -m "feat(backend): add configure_observability entrypoint and OTel Settings fields"
```

---

### Task 11: `docker-compose.yml` for current infrastructure services

**Files:**
- Create: `docker-compose.yml` (repo root)
- Create: `otel-collector-config.yaml` (repo root)
- Create: `.env.example` (repo root)

**Interfaces:**
- Consumes: nothing from application code — this task is pure infrastructure configuration.
- Produces: a `docker compose up` that starts `postgres`, `redis`, `minio`, and `otel-collector` — the four infrastructure services that exist as of this plan. No `backend`, `worker`, or `frontend` service is added yet since their Dockerfiles don't exist (Plans 3-5 append them).

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: agentdrops
      POSTGRES_PASSWORD: agentdrops
      POSTGRES_DB: agentdrops
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agentdrops"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio:latest
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 5s
      timeout: 5s
      retries: 5

  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    restart: unless-stopped
    command: ["--config=/etc/otel-collector-config.yaml"]
    volumes:
      - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
    environment:
      SIGNOZ_OTLP_ENDPOINT: ${SIGNOZ_OTLP_ENDPOINT:-localhost:4317}
      SIGNOZ_INGESTION_KEY: ${SIGNOZ_INGESTION_KEY:-}
    ports:
      - "4317:4317"
      - "4318:4318"

volumes:
  postgres_data:
  redis_data:
  minio_data:
```

- [ ] **Step 2: Write `otel-collector-config.yaml`**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch: {}

exporters:
  otlp/signoz:
    endpoint: ${env:SIGNOZ_OTLP_ENDPOINT}
    headers:
      signoz-ingestion-key: ${env:SIGNOZ_INGESTION_KEY}
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/signoz]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/signoz]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/signoz]
```

The default `SIGNOZ_OTLP_ENDPOINT=localhost:4317` (set in `docker-compose.yml`'s `environment:` block) lets the collector container start even with no `.env` file present — exports will simply fail at runtime with a connection error until a real SigNoz endpoint is configured, rather than the container failing to start. When pointing at SigNoz Cloud (TLS-terminated), change `tls.insecure` to `false` and set `SIGNOZ_OTLP_ENDPOINT`/`SIGNOZ_INGESTION_KEY` in `.env`.

- [ ] **Step 3: Write `.env.example`**

```bash
# LLM
ANTHROPIC_API_KEY=

# Web search tools
EXA_API_KEY=
TAVILY_API_KEY=
NEWSAPI_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=

# Postgres (matches docker-compose.yml defaults; override for non-local use)
DATABASE_URL=postgresql+asyncpg://agentdrops:agentdrops@localhost:5432/agentdrops

# Redis
REDIS_URL=redis://localhost:6379/0

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin

# Observability — backend/worker send OTLP here; this should point at the
# otel-collector service (localhost:4317 when running docker-compose locally
# and connecting from the host; use the service DNS name "otel-collector:4317"
# when the backend itself runs inside docker-compose).
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=agentdrops

# otel-collector's own upstream export target — a self-hosted or cloud SigNoz
# instance. Required for traces/metrics/logs to actually reach SigNoz; the
# collector will start without these set, but exports will fail silently.
SIGNOZ_OTLP_ENDPOINT=
SIGNOZ_INGESTION_KEY=
```

- [ ] **Step 4: Validate the compose file syntax**

Run: `docker compose config --quiet`
Expected: no output, exit code 0 (validates YAML syntax and variable interpolation without starting anything)

If `docker compose` is not available in this environment, report DONE_WITH_CONCERNS noting that validation step couldn't run, rather than skipping validation silently.

- [ ] **Step 5: Start the infrastructure services and verify health**

Run: `docker compose up -d postgres redis minio otel-collector`
Then: `docker compose ps` — expected all four services show as `running`/`healthy` (or `starting` transitioning to `healthy` within ~15s for postgres/redis/minio's healthchecks; `otel-collector` has no healthcheck defined here so just confirm it shows `running` and hasn't restarted).

Run: `docker compose logs otel-collector --tail 20` — expected no fatal startup errors (a connection-refused warning when it eventually tries to export to the placeholder `localhost:4317` upstream is expected and fine at this stage).

Then: `docker compose down`

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml otel-collector-config.yaml .env.example
git commit -m "feat: add docker-compose.yml for postgres, redis, minio, and otel-collector"
```

---

## Definition of Done

- `cd backend && uv run ruff check .` passes with zero violations.
- `cd backend && uv run mypy src` passes with zero errors.
- `cd backend && uv run pytest -v` passes (all tests across `resilience/`, `observability/`, and the migrated `webtools/`).
- All four search tools route their HTTP calls through a named circuit breaker wrapping a shared retry policy, and fail fast (without a network call) once their breaker is open.
- `configure_observability(settings)` wires tracing, metrics, and logging into one call; `agentdrops.logging` (Plan 1's structlog module) no longer exists.
- `docker compose up -d postgres redis minio otel-collector` starts all four services successfully.

## What's Next

Plan 3 builds the LangGraph research graph (`research/`), the `prompts/v1/` versioned prompt modules, and the headless `idearefine/` node — consuming `resilience/llm_retry.py` for Anthropic API calls and `observability/tracing.py`'s `traced_span` to wrap each graph node's execution. Plan 4 adds the `db/` module (Postgres repositories + Redis client), the FastAPI/arq service layer, and appends `backend` + `worker` services to `docker-compose.yml`. Plan 5 adds the Next.js frontend and appends its service to `docker-compose.yml`.
