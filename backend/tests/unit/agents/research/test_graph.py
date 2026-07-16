from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agentdrops.agents.research.graph import build_research_graph
from tests.unit.agents.conftest import FakeChatModel, make_settings


@tool
async def fake_search(query: str) -> str:
    """Fake search tool used only to drive the ReAct loop in tests."""
    return f"results for {query}"


def _ai_message_with_search_call(query: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "fake_search", "args": {"query": query}, "id": "call-1"}],
    )


async def test_research_graph_searches_then_compresses(monkeypatch: object) -> None:
    llm = FakeChatModel(
        [
            _ai_message_with_search_call("EV charging market"),
            AIMessage(content=""),  # no more tool calls -> compress
            AIMessage(content="Compressed findings on EV charging."),
        ]
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.research.graph.build_llm", lambda settings, **kw: llm
    )

    graph = build_research_graph(make_settings(), tools=[fake_search])
    result = await graph.ainvoke(
        {
            "researcher_messages": [],
            "research_topic": "EV charging market",
            "tool_call_iterations": 0,
            "compressed_research": "",
        }
    )

    assert result["compressed_research"] == "Compressed findings on EV charging."


async def test_research_graph_stops_at_iteration_cap(monkeypatch: object) -> None:
    llm = FakeChatModel(
        [
            _ai_message_with_search_call("topic"),  # iteration 1
            _ai_message_with_search_call("topic"),  # iteration 2 -> hits cap (max=2)
            AIMessage(content="Compressed despite still wanting to search."),
        ]
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.research.graph.build_llm", lambda settings, **kw: llm
    )

    settings = make_settings(max_tool_call_iterations=1)
    graph = build_research_graph(settings, tools=[fake_search])
    result = await graph.ainvoke(
        {
            "researcher_messages": [],
            "research_topic": "topic",
            "tool_call_iterations": 0,
            "compressed_research": "",
        }
    )

    assert result["compressed_research"] == "Compressed despite still wanting to search."
    assert result["tool_call_iterations"] == 1
