from langchain_core.messages import AIMessage, ToolMessage

from agentdrops.agents.supervisor.graph import build_supervisor_graph, get_notes_from_tool_calls
from tests.unit.agents.conftest import FakeChatModel, make_settings


class _FakeResearchGraph:
    """Stub research subgraph: echoes the delegated topic as its compressed finding."""

    async def ainvoke(self, state: dict) -> dict:
        topic = state["research_topic"]
        return {"compressed_research": f"findings on {topic}"}


def test_get_notes_from_tool_calls_filters_to_conduct_research() -> None:
    messages = [
        ToolMessage(content="findings A", tool_call_id="1", name="ConductResearch"),
        ToolMessage(content="reflection", tool_call_id="2", name="think_tool"),
    ]

    notes = get_notes_from_tool_calls(messages)

    assert notes == ["findings A"]


async def test_supervisor_fans_out_conduct_research_and_completes(monkeypatch: object) -> None:
    delegate = AIMessage(
        content="",
        tool_calls=[
            {"name": "ConductResearch", "args": {"research_topic": "topic A"}, "id": "call-1"},
            {"name": "ConductResearch", "args": {"research_topic": "topic B"}, "id": "call-2"},
        ],
    )
    complete = AIMessage(
        content="", tool_calls=[{"name": "ResearchComplete", "args": {}, "id": "call-3"}]
    )
    llm = FakeChatModel([delegate, complete])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.supervisor.graph.build_llm", lambda settings, **kw: llm
    )

    graph = build_supervisor_graph(make_settings(), _FakeResearchGraph())  # type: ignore[arg-type]
    result = await graph.ainvoke(
        {"supervisor_messages": [], "research_brief": "EV charging", "research_iterations": 0}
    )

    notes = get_notes_from_tool_calls(result["supervisor_messages"])
    assert set(notes) == {"findings on topic A", "findings on topic B"}


async def test_supervisor_stops_at_iteration_cap(monkeypatch: object) -> None:
    keep_delegating = AIMessage(
        content="",
        tool_calls=[{"name": "ConductResearch", "args": {"research_topic": "t"}, "id": "c"}],
    )
    llm = FakeChatModel([keep_delegating, keep_delegating])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.supervisor.graph.build_llm", lambda settings, **kw: llm
    )

    settings = make_settings(max_researcher_iterations=1)
    graph = build_supervisor_graph(settings, _FakeResearchGraph())  # type: ignore[arg-type]
    result = await graph.ainvoke(
        {"supervisor_messages": [], "research_brief": "brief", "research_iterations": 0}
    )

    assert result["research_iterations"] == 1
