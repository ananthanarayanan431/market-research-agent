"""Search-result pipeline: dedupe -> summarize -> format, shared by every search tool."""

import asyncio

from langchain_core.language_models import BaseChatModel

from agentdrops.agents.llm import ainvoke_with_retry
from agentdrops.agents.prompts import SUMMARIZE_PROMPT
from agentdrops.agents.schemas import Summary
from agentdrops.webtools.base import BaseSearchTool, SearchResult


def deduplicate_search_results(results: list[SearchResult]) -> list[SearchResult]:
    """Collapse duplicate URLs across search results, keeping the first occurrence of each."""
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        if result.url in seen:
            continue
        seen.add(result.url)
        deduped.append(result)
    return deduped


async def summarize_webpage_content(llm: BaseChatModel, content: str) -> Summary:
    """Summarize one page's content via LLM; falls back to a truncated excerpt on failure."""
    try:
        structured = llm.with_structured_output(Summary)
        summary = await ainvoke_with_retry(
            structured, SUMMARIZE_PROMPT.format(content=content[:8000])
        )
        return summary if isinstance(summary, Summary) else Summary.model_validate(summary)
    except Exception:
        return Summary(summary=content[:1000], key_excerpts="")


def format_search_output(summaries: list[tuple[SearchResult, Summary]]) -> str:
    """Render deduped, summarized results as a numbered SOURCE / URL / SUMMARY block."""
    if not summaries:
        return "No results found."
    blocks = [
        f"SOURCE {i}: {result.title}\nURL: {result.url}\nSUMMARY: {summary.summary}"
        for i, (result, summary) in enumerate(summaries, start=1)
    ]
    return "\n\n".join(blocks)


async def run_search_pipeline(
    search_tool: BaseSearchTool, llm: BaseChatModel, query: str, max_results: int
) -> str:
    """Search, dedupe, summarize each result, and format — the pipeline behind every search tool."""
    results = await search_tool.search(query, max_results=max_results)
    deduped = deduplicate_search_results(results)
    summarized = await asyncio.gather(
        *(summarize_webpage_content(llm, result.snippet) for result in deduped)
    )
    return format_search_output(list(zip(deduped, summarized, strict=True)))
