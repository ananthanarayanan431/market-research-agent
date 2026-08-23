"""Adapts the Context Hub search pipeline into a LangChain tool, the same shape as
agents/tools.py::make_tavily_tool."""

from langchain_core.tools import BaseTool, tool

from agentdrops.agents.contexthub.embeddings import EmbeddingClient
from agentdrops.agents.contexthub.methods import run_contexthub_search_pipeline
from agentdrops.repository.contexthub import ContextHubStore


def make_context_hub_tool(
    store: ContextHubStore, embedder: EmbeddingClient, top_k: int
) -> BaseTool:
    @tool
    async def context_hub_search(query: str) -> str:
        """Search uploaded enterprise documents and URLs (Context Hub) for content relevant
        to `query`. Only available when the user has opted in for this research turn."""
        return await run_contexthub_search_pipeline(store, embedder, query, top_k)

    return context_hub_search
