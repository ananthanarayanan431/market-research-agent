"""Request/response contracts for the v1 chat and research HTTP endpoints."""

from typing import Literal

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """One chat turn: an optional existing thread to resume, plus the user's message."""

    thread_id: str | None = None
    message: str


class ChatQueuedResponse(BaseModel):
    """Acknowledgement that one chat turn was enqueued; poll GET /research/{thread_id} or use
    /chat/stream to observe it. Replaces `ChatResponse`, which returned the turn's full result
    inline — no longer possible once the turn runs in a background worker."""

    thread_id: str
    status: Literal["queued"] = "queued"


class ResearchStatusResponse(BaseModel):
    """Current state of one research thread, read back from the graph's checkpoint."""

    thread_id: str
    status: Literal["queued", "clarifying", "running", "done", "failed"]
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
    status: Literal["queued", "clarifying", "running", "done", "failed"]


class SessionsResponse(BaseModel):
    sessions: list[SessionSummary]
