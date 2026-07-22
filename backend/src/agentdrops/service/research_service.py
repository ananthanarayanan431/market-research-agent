"""Research service: thread status and completed reports."""

from typing import Any

from agentdrops.api.v1.schema import ReportResponse, ResearchStatusResponse
from agentdrops.repository.sessions import SessionStore


class ResearchService:
    """Reads one research thread's status and completed report back out of storage."""

    def __init__(self, graph: Any, sessions: SessionStore) -> None:
        self._graph = graph
        self._sessions = sessions

    async def get_status(self, thread_id: str) -> ResearchStatusResponse | None:
        """Current state of one research thread: the session store's `failed` if set, else the
        graph's own checkpoint (a failed run may leave an incomplete checkpoint the graph can't
        classify). Returns `None` if `thread_id` is unknown to both."""
        session = await self._sessions.get(thread_id)
        if session is not None and session.status == "failed":
            return ResearchStatusResponse(
                thread_id=thread_id, status="failed", research_brief=None, report=None
            )

        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        state = await self._graph.aget_state(config)
        if not state.values:
            return None

        values = state.values
        if values.get("final_report"):
            research_status: str = "done"
        elif values.get("needs_clarification"):
            research_status = "clarifying"
        else:
            research_status = "running"

        return ResearchStatusResponse(
            thread_id=thread_id,
            status=research_status,  # type: ignore[arg-type]
            research_brief=values.get("research_brief") or None,
            report=values.get("final_report") or None,
        )

    async def get_report(self, thread_id: str) -> ReportResponse | None:
        """A completed thread's report and sources, so the drawer can reopen without a rerun.
        Returns `None` if the thread is unknown or hasn't produced a report yet."""
        session = await self._sessions.get(thread_id)
        if session is None or session.report is None:
            return None
        return ReportResponse(thread_id=thread_id, report=session.report, sources=session.sources)
