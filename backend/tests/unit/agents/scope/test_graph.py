from langchain_core.messages import HumanMessage

from agentdrops.agents.schemas import ClarifyWithUser, ResearchQuestion
from agentdrops.agents.scope.graph import build_scope_nodes, route_after_clarify
from tests.unit.agents.conftest import FakeChatModel, make_settings


async def test_clarify_with_user_asks_when_ambiguous(monkeypatch: object) -> None:
    llm = FakeChatModel(
        [ClarifyWithUser(need_clarification=True, question="Which region?", verification="")]
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.scope.graph.build_llm", lambda settings, **kw: llm
    )

    clarify_with_user, _ = build_scope_nodes(make_settings())
    result = await clarify_with_user({"messages": [HumanMessage(content="EV charging market")]})

    assert result["needs_clarification"] is True
    assert result["messages"][0].content == "Which region?"
    assert route_after_clarify({"needs_clarification": True}) == "__end__"


async def test_clarify_with_user_continues_when_clear(monkeypatch: object) -> None:
    llm = FakeChatModel(
        [ClarifyWithUser(need_clarification=False, question="", verification="Got it.")]
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.scope.graph.build_llm", lambda settings, **kw: llm
    )

    clarify_with_user, _ = build_scope_nodes(make_settings())
    result = await clarify_with_user(
        {"messages": [HumanMessage(content="EV charging market in the EU, 2025")]}
    )

    assert result["needs_clarification"] is False
    assert route_after_clarify(result) == "write_research_brief"


async def test_write_research_brief_seeds_supervisor_messages(monkeypatch: object) -> None:
    llm = FakeChatModel([ResearchQuestion(research_brief="Assess EU EV charging market, 2025.")])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.scope.graph.build_llm", lambda settings, **kw: llm
    )

    _, write_research_brief = build_scope_nodes(make_settings())
    result = await write_research_brief(
        {"messages": [HumanMessage(content="EV charging market in the EU, 2025")]}
    )

    assert result["research_brief"] == "Assess EU EV charging market, 2025."
    assert result["supervisor_messages"][0].content == "Assess EU EV charging market, 2025."
