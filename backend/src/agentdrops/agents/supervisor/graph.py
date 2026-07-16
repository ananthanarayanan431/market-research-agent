"""Supervisor graph: supervisor <-> supervisor_tools, fanning ConductResearch topics out."""

import asyncio
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentdrops.agents.llm import build_llm
from agentdrops.agents.prompts import LEAD_RESEARCHER_PROMPT, get_today_str
from agentdrops.agents.state import SupervisorState
from agentdrops.agents.tools import ConductResearch, ResearchComplete, think_tool
from agentdrops.config import Settings


def get_notes_from_tool_calls(messages: list[AnyMessage]) -> list[str]:
    """Extract ConductResearch findings from the supervisor's tool-call history for the writer."""
    return [
        str(m.content)
        for m in messages
        if isinstance(m, ToolMessage) and m.name == "ConductResearch"
    ]


def build_supervisor_graph(
    settings: Settings, research_graph: CompiledStateGraph[Any, Any, Any, Any]
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the supervisor graph: delegates via `research_graph`, loops until research ends."""
    llm = build_llm(settings).bind_tools([think_tool, ConductResearch, ResearchComplete])
    semaphore = asyncio.Semaphore(settings.max_concurrent_researchers)

    async def supervisor(state: SupervisorState) -> dict[str, object]:
        """Lead-researcher turn: decide whether to delegate more research or wrap up."""
        system = SystemMessage(
            content=LEAD_RESEARCHER_PROMPT.format(
                date=get_today_str(),
                research_brief=state["research_brief"],
                max_concurrent=settings.max_concurrent_researchers,
            )
        )
        response = await llm.ainvoke([system, *state["supervisor_messages"]])
        iterations = state.get("research_iterations", 0) + 1
        return {"supervisor_messages": [response], "research_iterations": iterations}

    async def run_topic(call: ToolCall) -> ToolMessage:
        """Run the research sub-agent on one delegated topic, bounded by the concurrency cap."""
        async with semaphore:
            result = await research_graph.ainvoke(
                {
                    "researcher_messages": [],
                    "research_topic": call["args"]["research_topic"],
                    "tool_call_iterations": 0,
                    "compressed_research": "",
                }
            )
        return ToolMessage(
            content=result["compressed_research"], tool_call_id=call["id"], name="ConductResearch"
        )

    async def supervisor_tools(state: SupervisorState) -> dict[str, object]:
        """Execute the supervisor's tool calls: reflect inline, fan ConductResearch topics out."""
        last = state["supervisor_messages"][-1]
        assert isinstance(last, AIMessage)
        research_calls = [c for c in last.tool_calls if c["name"] == "ConductResearch"]

        tool_messages: list[ToolMessage] = list(
            await asyncio.gather(*(run_topic(c) for c in research_calls))
        )
        for call in last.tool_calls:
            if call["name"] == "think_tool":
                reflection = call["args"].get("reflection", "")
                tool_messages.append(
                    ToolMessage(
                        content=f"Reflection recorded: {reflection}",
                        tool_call_id=call["id"],
                        name="think_tool",
                    )
                )
            elif call["name"] == "ResearchComplete":
                tool_messages.append(
                    ToolMessage(
                        content="Research marked complete.",
                        tool_call_id=call["id"],
                        name="ResearchComplete",
                    )
                )

        return {"supervisor_messages": tool_messages}

    def should_continue(state: SupervisorState) -> str:
        """Loop while delegating; stop on ResearchComplete, no tool calls, or the iteration cap."""
        last = state["supervisor_messages"][-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return END
        if any(c["name"] == "ResearchComplete" for c in last.tool_calls):
            return END
        if state.get("research_iterations", 0) >= settings.max_researcher_iterations:
            return END
        return "supervisor_tools"

    graph = StateGraph(SupervisorState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("supervisor_tools", supervisor_tools)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", should_continue, {"supervisor_tools": "supervisor_tools", END: END}
    )
    graph.add_edge("supervisor_tools", "supervisor")
    return graph.compile()
