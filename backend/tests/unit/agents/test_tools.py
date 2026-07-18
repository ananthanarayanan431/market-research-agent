from agentdrops.agents.schemas import Summary
from agentdrops.agents.tools import ConductResearch, ResearchComplete, make_tavily_tool, think_tool
from agentdrops.webtools.base import SearchResult
from tests.unit.agents.conftest import FakeChatModel


async def test_think_tool_returns_the_reflection() -> None:
    result = await think_tool.ainvoke({"reflection": "need one more source"})

    assert "need one more source" in result


class _FakeTavily:
    name = "tavily"

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        assert query == "EV charging market"
        return self._results


async def test_tavily_search_adapter_formats_summarized_results() -> None:
    results = [
        SearchResult(
            tool_name="tavily",
            title="EV charging report",
            url="https://example.com/ev",
            snippet="EV charging is growing fast.",
        )
    ]
    llm = FakeChatModel([Summary(summary="EV charging demand is rising.", key_excerpts="")])
    tool = make_tavily_tool(_FakeTavily(results), llm)  # type: ignore[arg-type]

    output = await tool.ainvoke({"query": "EV charging market", "max_results": 5})

    assert "SOURCE 1" in output
    assert "https://example.com/ev" in output
    assert "EV charging demand is rising." in output


def test_conduct_research_and_research_complete_schemas() -> None:
    call = ConductResearch(research_topic="EV charging incentives in the EU")
    assert call.research_topic == "EV charging incentives in the EU"
    ResearchComplete()
