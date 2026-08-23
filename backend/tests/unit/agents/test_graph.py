import httpx
from langgraph.checkpoint.memory import InMemorySaver

from agentdrops.agents.graph import build_market_researcher
from tests.unit.agents.conftest import make_settings


async def test_build_market_researcher_compiles_with_the_given_checkpointer() -> None:
    checkpointer = InMemorySaver()
    async with httpx.AsyncClient() as client:
        graph = build_market_researcher(make_settings(), client, checkpointer)

    assert graph.checkpointer is checkpointer


async def test_use_context_hub_true_adds_context_hub_search_tool(monkeypatch) -> None:
    captured_tools = {}

    def fake_build_research_graph(settings, tools):
        captured_tools["tools"] = tools
        from agentdrops.agents.research.graph import build_research_graph as real
        return real(settings, tools)

    monkeypatch.setattr(
        "agentdrops.agents.graph.build_research_graph", fake_build_research_graph
    )
    settings = make_settings()
    async with httpx.AsyncClient() as client:
        build_market_researcher(
            settings, client, InMemorySaver(),
            session_factory=object(), use_context_hub=True,
        )

    tool_names = {t.name for t in captured_tools["tools"]}
    assert "context_hub_search" in tool_names


async def test_use_context_hub_true_without_session_factory_raises() -> None:
    settings = make_settings()
    async with httpx.AsyncClient() as client:
        try:
            build_market_researcher(settings, client, InMemorySaver(), use_context_hub=True)
            raised = False
        except AssertionError:
            raised = True
    assert raised
