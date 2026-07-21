from langchain_core.messages import AIMessage

from agentdrops.agents.schemas import ReportPlan, ReportSection
from agentdrops.agents.writer.graph import build_writer_node
from tests.unit.agents.conftest import FakeChatModel, make_settings


class _RecordingChatModel(FakeChatModel):
    """FakeChatModel that also records every prompt it was invoked with, for assertions."""

    def __init__(self, responses: list[object]) -> None:
        super().__init__(responses)
        self.prompts: list[str] = []

    async def ainvoke(self, messages: object) -> object:
        self.prompts.append(str(messages[0].content))  # type: ignore[index]
        return await super().ainvoke(messages)


async def test_final_report_generation_plans_then_drafts_each_section(
    monkeypatch: object,
) -> None:
    plan = ReportPlan(
        sections=[
            ReportSection(title="Executive Summary", description="Overview.", target_words=250),
            ReportSection(title="Market Size", description="Sizing data.", target_words=300),
        ]
    )
    llm = _RecordingChatModel(
        [
            plan,
            AIMessage(content="The EV charging market is growing fast."),
            AIMessage(content="The market is projected to reach $50B by 2030."),
        ]
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.writer.graph.build_llm", lambda settings, **kw: llm
    )

    final_report_generation = build_writer_node(make_settings())
    result = await final_report_generation(
        {"research_brief": "EV charging market", "notes": ["finding one", "finding two"]}
    )

    assert result["final_report"] == (
        "## Executive Summary\n\nThe EV charging market is growing fast.\n\n"
        "## Market Size\n\nThe market is projected to reach $50B by 2030."
    )
    # Three LLM calls: one plan call, one per section.
    assert len(llm.prompts) == 3
    # The second section's prompt is seeded with the first section's finished text.
    assert "The EV charging market is growing fast." in llm.prompts[2]
    assert "Market Size" in llm.prompts[2]
    # The first section's prompt has nothing written yet.
    assert "(nothing written yet)" in llm.prompts[1]


async def test_final_report_generation_handles_no_notes(monkeypatch: object) -> None:
    plan = ReportPlan(
        sections=[ReportSection(title="Findings", description="Summarize.", target_words=200)]
    )
    llm = FakeChatModel([plan, AIMessage(content="No findings were available.")])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.writer.graph.build_llm", lambda settings, **kw: llm
    )

    final_report_generation = build_writer_node(make_settings())
    result = await final_report_generation({"research_brief": "EV charging market", "notes": []})

    assert result["final_report"] == "## Findings\n\nNo findings were available."


async def test_final_report_generation_falls_back_when_plan_has_no_sections(
    monkeypatch: object,
) -> None:
    llm = FakeChatModel([ReportPlan(sections=[]), AIMessage(content="Everything, synthesized.")])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.writer.graph.build_llm", lambda settings, **kw: llm
    )

    final_report_generation = build_writer_node(make_settings())
    result = await final_report_generation(
        {"research_brief": "EV charging market", "notes": ["finding one"]}
    )

    assert result["final_report"] == "## Findings\n\nEverything, synthesized."


async def test_final_report_generation_clamps_target_words_to_settings_bounds(
    monkeypatch: object,
) -> None:
    plan = ReportPlan(
        sections=[ReportSection(title="Overview", description="Overview.", target_words=99999)]
    )
    llm = _RecordingChatModel([plan, AIMessage(content="Body.")])
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentdrops.agents.writer.graph.build_llm", lambda settings, **kw: llm
    )

    settings = make_settings(report_min_words_per_section=100, report_max_words_per_section=400)
    final_report_generation = build_writer_node(settings)
    await final_report_generation({"research_brief": "EV charging market", "notes": []})

    assert "about 400 words" in llm.prompts[1]
