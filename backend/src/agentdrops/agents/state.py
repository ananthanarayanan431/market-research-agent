"""LangGraph state schemas and reducers shared across the agent pipeline."""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Top-level pipeline state: chat history in, final report out."""

    messages: Annotated[list[AnyMessage], add_messages]
    needs_clarification: bool
    research_brief: str
    supervisor_messages: Annotated[list[AnyMessage], add_messages]
    notes: Annotated[list[str], operator.add]
    final_report: str


class SupervisorState(TypedDict):
    """Supervisor subgraph state: delegates research and tracks how many turns it has taken."""

    supervisor_messages: Annotated[list[AnyMessage], add_messages]
    research_brief: str
    research_iterations: int


class ResearcherState(TypedDict):
    """Research sub-agent working state: one ReAct loop over a single delegated topic."""

    researcher_messages: Annotated[list[AnyMessage], add_messages]
    research_topic: str
    tool_call_iterations: int
    compressed_research: str


class ResearcherOutputState(TypedDict):
    """Trimmed surface a research sub-agent returns to the supervisor."""

    compressed_research: str
    researcher_messages: Annotated[list[AnyMessage], add_messages]
