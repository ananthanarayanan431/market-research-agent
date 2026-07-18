from agentdrops.agents.research.methods import (
    deduplicate_search_results,
    format_search_output,
    run_search_pipeline,
    summarize_webpage_content,
)
from agentdrops.agents.schemas import Summary
from agentdrops.webtools.base import SearchResult
from tests.unit.agents.conftest import FakeChatModel


def _result(url: str, title: str = "title", snippet: str = "snippet") -> SearchResult:
    return SearchResult(tool_name="tavily", title=title, url=url, snippet=snippet)


def test_deduplicate_search_results_collapses_duplicate_urls() -> None:
    results = [_result("https://a.com"), _result("https://b.com"), _result("https://a.com")]

    deduped = deduplicate_search_results(results)

    assert [r.url for r in deduped] == ["https://a.com", "https://b.com"]


async def test_summarize_webpage_content_returns_structured_summary() -> None:
    llm = FakeChatModel([Summary(summary="concise summary", key_excerpts="quote")])

    summary = await summarize_webpage_content(llm, "long page content")  # type: ignore[arg-type]

    assert summary.summary == "concise summary"


async def test_summarize_webpage_content_falls_back_on_failure() -> None:
    class _BrokenLLM:
        def with_structured_output(self, schema: object) -> "_BrokenLLM":
            return self

        async def ainvoke(self, _prompt: str) -> None:
            raise RuntimeError("model unavailable")

    summary = await summarize_webpage_content(_BrokenLLM(), "x" * 2000)  # type: ignore[arg-type]

    assert summary.summary == ("x" * 2000)[:1000]
    assert summary.key_excerpts == ""


def test_format_search_output_renders_numbered_sources() -> None:
    summaries = [(_result("https://a.com", title="A"), Summary(summary="s1", key_excerpts=""))]

    output = format_search_output(summaries)

    assert "SOURCE 1: A" in output
    assert "https://a.com" in output
    assert "SUMMARY: s1" in output


def test_format_search_output_handles_no_results() -> None:
    assert format_search_output([]) == "No results found."


async def test_run_search_pipeline_dedupes_and_formats() -> None:
    class _FakeTool:
        async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
            return [_result("https://a.com"), _result("https://a.com")]

    llm = FakeChatModel([Summary(summary="only once", key_excerpts="")])

    output = await run_search_pipeline(_FakeTool(), llm, "query", 5)  # type: ignore[arg-type]

    assert output.count("SOURCE") == 1
    assert "only once" in output
