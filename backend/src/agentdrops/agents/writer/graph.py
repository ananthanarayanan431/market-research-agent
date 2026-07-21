"""Writer node: `final_report_generation` synthesizes research notes into the final report.

Uses the plan-then-write recipe from THUDM/LongWriter's AgentWrite pipeline
(https://github.com/THUDM/LongWriter): asking one LLM call for an entire long report collapses
its output toward the model's typical response length, well short of a thorough report. Instead,
a structured planning call breaks the report into sections with word-count targets, then each
section is drafted with its own LLM call, seeded with everything written so far so it stays
on-topic and doesn't repeat earlier sections. The drafts are concatenated in order for the final
report.
"""

from collections.abc import Awaitable, Callable

from langchain_core.messages import SystemMessage

from agentdrops.agents.llm import ainvoke_with_retry, build_llm
from agentdrops.agents.prompts import (
    REPORT_PLAN_PROMPT,
    REPORT_SECTION_PROMPT,
    get_today_str,
)
from agentdrops.agents.schemas import ReportPlan, ReportSection
from agentdrops.agents.state import AgentState
from agentdrops.config import Settings

WriterNode = Callable[[AgentState], Awaitable[dict[str, object]]]


def _format_plan(sections: list[ReportSection]) -> str:
    """Render the section plan as a numbered outline, for the per-section prompt's context."""
    return "\n".join(
        f"{i}. {section.title} (~{section.target_words} words) — {section.description}"
        for i, section in enumerate(sections, start=1)
    )


def build_writer_node(settings: Settings) -> WriterNode:
    """Build the `final_report_generation` node, bound to one LLM."""
    llm = build_llm(settings, temperature=0.2)
    plan_llm = llm.with_structured_output(ReportPlan)

    async def final_report_generation(state: AgentState) -> dict[str, object]:
        """Plan the report's sections, then draft each one in turn, seeded on prior sections."""
        findings = "\n\n---\n\n".join(state.get("notes", [])) or "No findings were gathered."
        research_brief = state["research_brief"]
        date = get_today_str()

        plan_prompt = REPORT_PLAN_PROMPT.format(
            date=date,
            research_brief=research_brief,
            findings=findings,
            min_words=settings.report_min_words_per_section,
            max_words=settings.report_max_words_per_section,
            min_sections=settings.report_min_sections,
            max_sections=settings.report_max_sections,
        )
        plan = await ainvoke_with_retry(plan_llm, [SystemMessage(content=plan_prompt)])
        assert isinstance(plan, ReportPlan)
        sections = plan.sections or [
            ReportSection(
                title="Findings",
                description="Synthesize all findings into one coherent, well-cited narrative.",
                target_words=settings.report_max_words_per_section,
            )
        ]
        plan_text = _format_plan(sections)

        written_parts: list[str] = []
        for section in sections:
            target_words = max(
                settings.report_min_words_per_section,
                min(section.target_words, settings.report_max_words_per_section),
            )
            is_final_hint = (
                "This is the final section — you may close out the report."
                if section is sections[-1]
                else "This is not the final section — do not write a conclusion yet."
            )
            section_prompt = REPORT_SECTION_PROMPT.format(
                date=date,
                research_brief=research_brief,
                findings=findings,
                plan=plan_text,
                written_so_far="\n\n".join(written_parts) or "(nothing written yet)",
                section_title=section.title,
                section_description=section.description,
                target_words=target_words,
                is_final_hint=is_final_hint,
            )
            response = await ainvoke_with_retry(llm, [SystemMessage(content=section_prompt)])
            body = str(response.content).strip()
            written_parts.append(f"## {section.title}\n\n{body}")

        return {"final_report": "\n\n".join(written_parts)}

    return final_report_generation
