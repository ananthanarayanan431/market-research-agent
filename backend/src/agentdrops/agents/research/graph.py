"""Research sub-agent graph: a ReAct loop (search <-> reflect) that compresses findings."""

from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentdrops.agents.llm import build_llm
from agentdrops.agents.prompts import COMPRESS_PROMPT, RESEARCH_AGENT_PROMPT, get_today_str
from agentdrops.agents.state import ResearcherState
from agentdrops.config import Settings


def build_research_graph(
    settings: Settings, tools: list[BaseTool]
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the research sub-agent graph: llm_call <-> tool_node -> compress_research -> END."""
    llm = build_llm(settings)
    llm_with_tools = llm.bind_tools(tools)
    tools_by_name = {tool_.name: tool_ for tool_ in tools}

    async def llm_call(state: ResearcherState) -> dict[str, object]:
        """Ask the model whether to search more on `research_topic` or stop and compress."""
        system = SystemMessage(content=RESEARCH_AGENT_PROMPT.format(date=get_today_str()))
        is_first_turn = not state["researcher_messages"]
        messages = state["researcher_messages"] or [HumanMessage(content=state["research_topic"])]
        response = await llm_with_tools.ainvoke([system, *messages])
        if is_first_turn:
            return {"researcher_messages": [messages[0], response]}
        return {"researcher_messages": [response]}

    async def tool_node(state: ResearcherState) -> dict[str, object]:
        """Execute every tool call the model just requested and append the observations."""
        last = state["researcher_messages"][-1]
        assert isinstance(last, AIMessage)
        outputs = []
        for call in last.tool_calls:
            tool_ = tools_by_name.get(call["name"])
            if tool_ is None:
                content = f"Error: tool '{call['name']}' does not exist."
            else:
                content = str(await tool_.ainvoke(call["args"]))
            outputs.append(ToolMessage(content=content, tool_call_id=call["id"]))
        iterations = state.get("tool_call_iterations", 0) + 1
        return {"researcher_messages": outputs, "tool_call_iterations": iterations}

    def should_continue(state: ResearcherState) -> Literal["tool_node", "compress_research"]:
        """Keep researching while the model requested tools and the iteration cap isn't hit."""
        last = state["researcher_messages"][-1]
        requested_tools = isinstance(last, AIMessage) and bool(last.tool_calls)
        under_cap = state.get("tool_call_iterations", 0) < settings.max_tool_call_iterations
        return "tool_node" if requested_tools and under_cap else "compress_research"

    async def compress_research(state: ResearcherState) -> dict[str, object]:
        """Condense the full message trail into a single research summary for the supervisor."""
        system = SystemMessage(content=COMPRESS_PROMPT)
        closing = HumanMessage(content="Compress the research above into findings on this topic.")
        response = await llm.ainvoke([system, *state["researcher_messages"], closing])
        return {"compressed_research": str(response.content)}

    graph = StateGraph(ResearcherState)
    graph.add_node("llm_call", llm_call)
    graph.add_node("tool_node", tool_node)
    graph.add_node("compress_research", compress_research)
    graph.add_edge(START, "llm_call")
    graph.add_conditional_edges(
        "llm_call",
        should_continue,
        {"tool_node": "tool_node", "compress_research": "compress_research"},
    )
    graph.add_edge("tool_node", "llm_call")
    graph.add_edge("compress_research", END)
    return graph.compile()
