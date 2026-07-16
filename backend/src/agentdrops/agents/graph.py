"""Top-level pipeline: clarify -> brief -> supervisor -> writer, compiled as one LangGraph graph."""

from typing import Any

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentdrops.agents.llm import build_llm
from agentdrops.agents.research.graph import build_research_graph
from agentdrops.agents.scope.graph import build_scope_nodes, route_after_clarify
from agentdrops.agents.state import AgentState
from agentdrops.agents.supervisor.graph import build_supervisor_graph, get_notes_from_tool_calls
from agentdrops.agents.tools import make_tavily_tool, think_tool
from agentdrops.agents.writer.graph import build_writer_node
from agentdrops.config import Settings
from agentdrops.webtools.tavily import TavilySearchTool


def build_market_researcher(
    settings: Settings, client: httpx.AsyncClient
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the full market-research pipeline, with Tavily wired in as the only search tool.

    Other search tools (exa/news/reddit) drop in later by adding them to the `tools` list passed
    to `build_research_graph` — no changes needed elsewhere in the pipeline.
    """
    tavily = TavilySearchTool(api_key=settings.tavily_api_key, client=client)
    summarizer_llm = build_llm(settings)
    tavily_search = make_tavily_tool(tavily, summarizer_llm)

    research_graph = build_research_graph(settings, tools=[tavily_search, think_tool])
    supervisor_graph = build_supervisor_graph(settings, research_graph)
    clarify_with_user, write_research_brief = build_scope_nodes(settings)
    final_report_generation = build_writer_node(settings)

    async def supervisor(state: AgentState) -> dict[str, object]:
        """Run the supervisor subgraph to completion and surface its findings as `notes`."""
        result = await supervisor_graph.ainvoke(
            {
                "supervisor_messages": state["supervisor_messages"],
                "research_brief": state["research_brief"],
                "research_iterations": 0,
            }
        )
        return {"notes": get_notes_from_tool_calls(result["supervisor_messages"])}

    graph = StateGraph[AgentState, None, AgentState, AgentState](AgentState)
    graph.add_node("clarify_with_user", clarify_with_user)  # type: ignore[call-overload]
    graph.add_node("write_research_brief", write_research_brief)  # type: ignore[call-overload]
    graph.add_node("supervisor", supervisor)
    graph.add_node("final_report_generation", final_report_generation)  # type: ignore[arg-type]

    graph.add_edge(START, "clarify_with_user")
    graph.add_conditional_edges(
        "clarify_with_user",
        route_after_clarify,
        {"write_research_brief": "write_research_brief", END: END},
    )
    graph.add_edge("write_research_brief", "supervisor")
    graph.add_edge("supervisor", "final_report_generation")
    graph.add_edge("final_report_generation", END)

    return graph.compile(checkpointer=InMemorySaver())
