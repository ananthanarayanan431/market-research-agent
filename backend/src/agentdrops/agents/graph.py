"""Top-level pipeline: clarify -> brief -> supervisor -> writer, compiled as one LangGraph graph."""

from typing import Any, cast

import httpx
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentdrops.agents.contexthub.embeddings import EmbeddingClient
from agentdrops.agents.contexthub.tools import make_context_hub_tool
from agentdrops.agents.llm import build_llm
from agentdrops.agents.research.graph import build_research_graph
from agentdrops.agents.scope.graph import build_scope_nodes, route_after_clarify
from agentdrops.agents.state import AgentState, SupervisorState
from agentdrops.agents.supervisor.graph import build_supervisor_graph, get_notes_from_tool_calls
from agentdrops.agents.tools import make_tavily_tool, think_tool
from agentdrops.agents.writer.graph import build_writer_node
from agentdrops.config import Settings
from agentdrops.repository.contexthub import ContextHubStore
from agentdrops.webtools.tavily import TavilySearchTool


def build_market_researcher(
    settings: Settings,
    client: httpx.AsyncClient,
    checkpointer: BaseCheckpointSaver[Any],
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    use_context_hub: bool = False,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the full market-research pipeline. `tavily_search`/`think_tool` are always
    available; `context_hub_search` is included only when `use_context_hub` is True (a
    per-turn opt-in — see worker/tasks.py), which requires `session_factory` to build its
    `ContextHubStore`.
    """
    tavily = TavilySearchTool(api_key=settings.tavily_api_key, client=client)
    summarizer_llm = build_llm(settings)
    tavily_search = make_tavily_tool(tavily, summarizer_llm)
    tools: list[Any] = [tavily_search, think_tool]

    if use_context_hub:
        assert session_factory is not None, "use_context_hub=True requires a session_factory"
        contexthub_store = ContextHubStore(session_factory)
        embedder = EmbeddingClient(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            client=client,
        )
        tools.append(
            make_context_hub_tool(
                contexthub_store, embedder, top_k=settings.contexthub_search_top_k
            )
        )

    research_graph = build_research_graph(settings, tools=tools)
    supervisor_graph = build_supervisor_graph(settings, research_graph)
    clarify_with_user, write_research_brief = build_scope_nodes(settings)
    final_report_generation = build_writer_node(settings)

    async def supervisor(state: AgentState) -> dict[str, object]:
        """Run the supervisor subgraph to completion and surface its findings as `notes`.

        Streamed via `astream` (not `ainvoke`) and re-emitted through this node's own writer:
        a bare nested `ainvoke()` starts an isolated run whose `custom` writes (the
        progress/source events `run_topic` emits) would otherwise never reach the outer
        `/chat/stream` consumer — nothing drains them without a stream loop over this call.
        """
        writer = get_stream_writer()
        final_state: SupervisorState | None = None
        async for stream_type, chunk in supervisor_graph.astream(
            {
                "supervisor_messages": state["supervisor_messages"],
                "research_brief": state["research_brief"],
                "research_iterations": 0,
            },
            stream_mode=["custom", "values"],
        ):
            if stream_type == "custom":
                writer(chunk)
            else:
                final_state = cast(SupervisorState, chunk)
        assert final_state is not None
        return {"notes": get_notes_from_tool_calls(final_state["supervisor_messages"])}

    graph = StateGraph[AgentState, None, AgentState, AgentState](AgentState)
    graph.add_node("clarify_with_user", clarify_with_user)  # type: ignore
    graph.add_node("write_research_brief", write_research_brief)  # type: ignore
    graph.add_node("supervisor", supervisor)
    graph.add_node("final_report_generation", final_report_generation)  # type: ignore

    graph.add_edge(START, "clarify_with_user")
    graph.add_conditional_edges(
        "clarify_with_user",
        route_after_clarify,
        {"write_research_brief": "write_research_brief", END: END},
    )
    graph.add_edge("write_research_brief", "supervisor")
    graph.add_edge("supervisor", "final_report_generation")
    graph.add_edge("final_report_generation", END)

    return graph.compile(checkpointer=checkpointer)
