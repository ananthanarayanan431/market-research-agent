from langchain_core.messages import AIMessage

from agentdrops.agents.writer.graph import build_writer_node
from tests.unit.agents.conftest import FakeChatModel, make_settings


async def test_final_report_generation_joins_notes_into_report(monkeypatch: object) -> None:
    llm = FakeChatModel([AIMessage(content="# EV Charging Market Report\n\n...findings...")])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.writer.graph.build_llm", lambda settings, **kw: llm
    )

    final_report_generation = build_writer_node(make_settings())
    result = await final_report_generation(
        {"research_brief": "EV charging market", "notes": ["finding one", "finding two"]}
    )

    assert result["final_report"] == "# EV Charging Market Report\n\n...findings..."


async def test_final_report_generation_handles_no_notes(monkeypatch: object) -> None:
    llm = FakeChatModel([AIMessage(content="No findings were available.")])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.writer.graph.build_llm", lambda settings, **kw: llm
    )

    final_report_generation = build_writer_node(make_settings())
    result = await final_report_generation({"research_brief": "EV charging market", "notes": []})

    assert result["final_report"] == "No findings were available."
