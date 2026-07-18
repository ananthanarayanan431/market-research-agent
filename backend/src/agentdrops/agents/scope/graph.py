"""Scope nodes: `clarify_with_user` and `write_research_brief`, the graph's entry stage."""

from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END

from agentdrops.agents.llm import build_llm
from agentdrops.agents.prompts import CLARIFY_PROMPT, TRANSFORM_BRIEF_PROMPT, get_today_str
from agentdrops.agents.schemas import ClarifyWithUser, ResearchQuestion
from agentdrops.agents.state import AgentState
from agentdrops.config import Settings

ScopeNode = Callable[[AgentState], Awaitable[dict[str, object]]]


def build_scope_nodes(settings: Settings) -> tuple[ScopeNode, ScopeNode]:
    """Build the `clarify_with_user` and `write_research_brief` node functions, bound to one LLM."""
    llm = build_llm(settings)
    clarify_llm = llm.with_structured_output(ClarifyWithUser)
    brief_llm = llm.with_structured_output(ResearchQuestion)

    async def clarify_with_user(state: AgentState) -> dict[str, object]:
        """Ask the model whether the request needs clarification before research starts."""
        system = SystemMessage(content=CLARIFY_PROMPT.format(date=get_today_str()))
        result = await clarify_llm.ainvoke([system, *state["messages"]])
        assert isinstance(result, ClarifyWithUser)
        reply = result.question if result.need_clarification else result.verification
        return {
            "messages": [AIMessage(content=reply)],
            "needs_clarification": result.need_clarification,
        }

    async def write_research_brief(state: AgentState) -> dict[str, object]:
        """Distill the chat history into a single research brief that seeds the supervisor."""
        system = SystemMessage(content=TRANSFORM_BRIEF_PROMPT.format(date=get_today_str()))
        result = await brief_llm.ainvoke([system, *state["messages"]])
        assert isinstance(result, ResearchQuestion)
        return {
            "research_brief": result.research_brief,
            "supervisor_messages": [HumanMessage(content=result.research_brief)],
        }

    return clarify_with_user, write_research_brief


def route_after_clarify(state: AgentState) -> str:
    """Route: end the turn if a clarifying question was asked, otherwise continue to the brief."""
    return END if state.get("needs_clarification") else "write_research_brief"
