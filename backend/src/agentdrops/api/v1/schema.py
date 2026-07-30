"""Request/response contracts for the v1 chat and research HTTP endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


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
    clarify_question: str | None = None
    clarify_suggestions: list[str] = Field(default_factory=list)


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
    pinned: bool = False


class SessionsResponse(BaseModel):
    sessions: list[SessionSummary]


class StarterSuggestionsResponse(BaseModel):
    """Example research prompts for the idle chat state."""

    prompts: list[str]


class UpdateSessionRequest(BaseModel):
    """Partial update for a session: rename it, pin/unpin it, or both in one call."""

    title: str | None = None
    pinned: bool | None = None
