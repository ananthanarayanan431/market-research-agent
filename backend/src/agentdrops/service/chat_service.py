"""Chat service: drives one LangGraph research turn, streamed or collected whole."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage

from agentdrops.config.constants import CHAT_NODE_LABELS, CHAT_TITLE_MAX_LENGTH
from agentdrops.observability.logging import bind_run_id
from agentdrops.observability.tracing import traced_span
from agentdrops.repository.audit import AuditLog
from agentdrops.repository.sessions import SessionStore

logger = logging.getLogger(__name__)


class ChatService:
    """Owns the single call site for `graph.astream`.

    `run_turn` is called by the Celery worker (`worker/runner.py::run_turn`), not directly by
    `/v1/chat`/`/v1/chat/stream` — those routes only enqueue a task now. The worker republishes
    every yielded event to Redis pub/sub, which `/v1/chat/stream` relays to the client and
    `/v1/chat` (via GET /research/{thread_id}) can be polled for instead.
    """

    def __init__(self, graph: Any, sessions: SessionStore, audit: AuditLog) -> None:
        self._graph = graph
        self._sessions = sessions
        self._audit = audit

    async def run_turn(
        self, thread_id: str, message: str, *, operation: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Advance one turn to completion, yielding every SSE-shaped event along the way.

        The whole turn runs inside one `research.turn` span, and inside `bind_run_id(thread_id)`
        so every log line emitted anywhere in the graph carries the thread it belongs to — that
        is what makes a single run filterable end-to-end in SigNoz. `operation` tags the audit
        row so `/chat` and `/chat/stream` calls stay distinguishable in the trail.
        """
        await self._sessions.touch(thread_id, title=message[:CHAT_TITLE_MAX_LENGTH])
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        inputs = {"messages": [HumanMessage(content=message)]}

        with bind_run_id(thread_id), traced_span("research.turn", thread_id=thread_id) as span:
            outcome = "incomplete"
            try:
                async for stream_type, chunk in self._graph.astream(
                    inputs, config=config, stream_mode=["updates", "custom"]
                ):
                    if stream_type == "custom":
                        if chunk.get("type") == "source":
                            await self._sessions.add_source(
                                thread_id, chunk["topic"], chunk["summary"]
                            )
                            span.add_event("research.source", {"topic": chunk["topic"]})
                        yield chunk
                        continue
                    for node_name, node_output in chunk.items():
                        if node_name == "clarify_with_user" and node_output.get(
                            "needs_clarification"
                        ):
                            question = str(node_output["messages"][-1].content)
                            suggestions = list(node_output.get("clarify_suggestions", []))
                            await self._sessions.set_status(
                                thread_id,
                                "clarifying",
                                clarify_question=question,
                                clarify_suggestions=suggestions,
                            )
                            outcome = "clarify"
                            await self._audit.record(
                                thread_id, operation=operation, status="clarify"
                            )
                            yield {
                                "type": "clarify",
                                "thread_id": thread_id,
                                "response": question,
                                "suggestions": suggestions,
                            }
                            return
                        if node_name == "final_report_generation":
                            report = node_output["final_report"]
                            await self._sessions.set_status(thread_id, "done", report=report)
                            outcome = "done"
                            span.set_attribute("research.report_chars", len(report))
                            await self._audit.record(
                                thread_id,
                                operation=operation,
                                status="done",
                                detail={"report_chars": len(report)},
                            )
                            yield {"type": "done", "thread_id": thread_id, "report": report}
                            return
                        if node_name == "supervisor":
                            await self._sessions.set_status(thread_id, "running")
                        label = CHAT_NODE_LABELS.get(node_name)
                        if label:
                            span.add_event("research.stage", {"stage": label})
                            yield {"type": "progress", "step": label}
            finally:
                span.set_attribute("research.outcome", outcome)

    async def record_failure(self, thread_id: str, *, operation: str, error: str) -> None:
        """Record a failed turn: session status plus an audit entry. Called by the Celery
        worker's except block (`worker/runner.py::run_turn`), not by the routes directly.

        Both persistence calls are best-effort and independent: the worker still needs to publish
        its own terminal "error" event to Redis regardless of whether either write below succeeds,
        so a failure here must not raise and prevent that from happening.
        """
        try:
            await self._sessions.set_status(thread_id, "failed", error=error)
        except Exception:
            logger.exception("failed to set session status to failed for thread_id=%s", thread_id)
        try:
            await self._audit.record(
                thread_id, operation=operation, status="failed", detail={"error": error}
            )
        except Exception:
            logger.exception("failed to record failure audit entry for thread_id=%s", thread_id)
