"""In-memory session registry: title/status/report/sources per thread.

Backs the sidebar listing and the reopen-a-completed-run endpoints. Lives only for the process
lifetime, same as the compiled graph's `InMemorySaver` checkpointer — swap both for persistent
stores (e.g. Postgres) together if runs need to survive a restart.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

Status = Literal["clarifying", "running", "done"]


@dataclass
class SessionRecord:
    """One research thread's session-level metadata, as opposed to the graph's own state."""

    thread_id: str
    title: str
    created_at: datetime
    status: Status = "clarifying"
    report: str | None = None
    sources: list[dict[str, str]] = field(default_factory=list)


class SessionStore:
    """Tracks one `SessionRecord` per thread_id, keyed by first sight of that thread."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}

    def touch(self, thread_id: str, *, title: str) -> SessionRecord:
        """Create a session record the first time a thread is seen; a no-op afterward."""
        return self._sessions.setdefault(
            thread_id,
            SessionRecord(thread_id=thread_id, title=title, created_at=datetime.now(UTC)),
        )

    def set_status(self, thread_id: str, status: Status, *, report: str | None = None) -> None:
        session = self._sessions.get(thread_id)
        if session is None:
            return
        session.status = status
        if report is not None:
            session.report = report

    def add_source(self, thread_id: str, topic: str, summary: str) -> None:
        session = self._sessions.get(thread_id)
        if session is not None:
            session.sources.append({"topic": topic, "summary": summary})

    def get(self, thread_id: str) -> SessionRecord | None:
        return self._sessions.get(thread_id)

    def list_recent(self) -> list[SessionRecord]:
        return sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)
