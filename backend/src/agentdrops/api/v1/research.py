"""Research endpoints: thread status and completed reports (see `sessions.py` for listing)."""

from typing import Any

from fastapi import APIRouter, Request, status

from agentdrops.api.v1.schema import ReportResponse, ResearchStatusResponse
from agentdrops.repository.sessions import SessionStore
from agentdrops.types.error_codes import NotFoundError, fastAPIErrorResponseModels
from agentdrops.types.response import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/research", tags=["research"])


@router.get(
    "/{thread_id}",
    response_model=SuccessResponse[ResearchStatusResponse],
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def get_research_status(
    request: Request, thread_id: str
) -> SuccessResponse[ResearchStatusResponse]:
    """Read one thread's current status: the session store's `failed` if set, else the graph's
    own checkpoint (a failed run may leave an incomplete checkpoint the graph can't classify)."""
    sessions: SessionStore = request.app.state.sessions
    session = sessions.get(thread_id)
    if session is not None and session.status == "failed":
        return SuccessResponse(
            data=ResearchStatusResponse(
                thread_id=thread_id, status="failed", research_brief=None, report=None
            )
        )

    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    graph = request.app.state.graph
    state = await graph.aget_state(config)
    if not state.values:
        raise ErrorResponse(NotFoundError(message="Unknown thread_id"))

    values = state.values
    if values.get("final_report"):
        research_status: str = "done"
    elif values.get("needs_clarification"):
        research_status = "clarifying"
    else:
        research_status = "running"

    return SuccessResponse(
        data=ResearchStatusResponse(
            thread_id=thread_id,
            status=research_status,  # type: ignore[arg-type]
            research_brief=values.get("research_brief") or None,
            report=values.get("final_report") or None,
        )
    )


@router.get(
    "/{thread_id}/report",
    response_model=SuccessResponse[ReportResponse],
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def get_research_report(request: Request, thread_id: str) -> SuccessResponse[ReportResponse]:
    """Fetch a completed thread's report and sources, so the drawer can reopen without a rerun."""
    sessions: SessionStore = request.app.state.sessions
    session = sessions.get(thread_id)
    if session is None or session.report is None:
        raise ErrorResponse(NotFoundError(message="Report not available for this thread_id"))

    return SuccessResponse(
        data=ReportResponse(thread_id=thread_id, report=session.report, sources=session.sources)
    )
