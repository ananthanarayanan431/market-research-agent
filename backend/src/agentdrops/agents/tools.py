"""Tools bound to agent LLM calls: reflection, delegation signals, and the Tavily search adapter."""

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from agentdrops.agents.research.methods import run_search_pipeline
from agentdrops.webtools.tavily import TavilySearchTool


@tool
def think_tool(reflection: str) -> str:
    """Record a strategic reflection between searches — a deliberate pause to plan the next search
    or decide research is complete. No I/O; call this before deciding to search again or stop."""
    return f"Reflection recorded: {reflection}"


def make_tavily_tool(tavily: TavilySearchTool, llm: BaseChatModel) -> BaseTool:
    """Adapt the existing resilient `TavilySearchTool` into a LangChain tool named `tavily_search`.

    This only wires Tavily's interface: it delegates to the shared search -> summarize -> format
    pipeline in `agents/research/methods.py`, and to `TavilySearchTool.search()` for the HTTP call
    itself (retry + circuit breaker already applied there). No HTTP or summarization logic here.
    """

    @tool
    async def tavily_search(query: str, max_results: int = 5) -> str:
        """Search the web via Tavily for market-research sources on `query`."""
        return await run_search_pipeline(tavily, llm, query, max_results)

    return tavily_search


class ConductResearch(BaseModel):
    """Delegate one focused research topic to a research sub-agent. Call once per distinct topic."""

    research_topic: str = Field(description="A single, focused research topic to investigate.")


class ResearchComplete(BaseModel):
    """Signal that enough research has been gathered; ends the supervisor's delegation loop."""
