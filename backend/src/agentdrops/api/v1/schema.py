"""Request/response contracts for the v1 chat and research HTTP endpoints."""

from typing import Literal

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """One chat turn: an optional existing thread to resume, plus the user's message."""

    thread_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    """One chat turn's result: which thread it belongs to, the reply, and the report once ready."""

    thread_id: str
    response: str
    is_followup: bool
    report: str | None = None


class ResearchStatusResponse(BaseModel):
    """Current state of one research thread, read back from the graph's checkpoint."""

    thread_id: str
    status: Literal["clarifying", "running", "done", "failed"]
    research_brief: str | None = None
    report: str | None = None


class ReportResponse(BaseModel):
    """A completed thread's report, for reopening the drawer without re-running research."""

    thread_id: str
    report: str
    sources: list[dict[str, str]]


class SessionSummary(BaseModel):
    """One row in the recent-sessions sidebar."""

    id: str
    title: str
    created_at: str
    status: Literal["clarifying", "running", "done", "failed"]


class SessionsResponse(BaseModel):
    sessions: list[SessionSummary]
