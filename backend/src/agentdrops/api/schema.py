"""Request/response contracts for the chat HTTP endpoint."""

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
