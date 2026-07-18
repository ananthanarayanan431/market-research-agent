"""Writer node: `final_report_generation` synthesizes research notes into the final report."""

from collections.abc import Awaitable, Callable

from langchain_core.messages import SystemMessage

from agentdrops.agents.llm import ainvoke_with_retry, build_llm
from agentdrops.agents.prompts import FINAL_REPORT_PROMPT, get_today_str
from agentdrops.agents.state import AgentState
from agentdrops.config import Settings

WriterNode = Callable[[AgentState], Awaitable[dict[str, object]]]


def build_writer_node(settings: Settings) -> WriterNode:
    """Build the `final_report_generation` node, bound to one LLM."""
    llm = build_llm(settings, temperature=0.2)

    async def final_report_generation(state: AgentState) -> dict[str, object]:
        """Join all research notes and ask the model to synthesize the final cited report."""
        findings = "\n\n---\n\n".join(state.get("notes", [])) or "No findings were gathered."
        prompt = FINAL_REPORT_PROMPT.format(
            date=get_today_str(), research_brief=state["research_brief"], findings=findings
        )
        response = await ainvoke_with_retry(llm, [SystemMessage(content=prompt)])
        return {"final_report": str(response.content)}

    return final_report_generation
