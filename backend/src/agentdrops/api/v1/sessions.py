"""Session-listing endpoint: recent research threads for the sidebar."""

from fastapi import APIRouter, Request

from agentdrops.api.v1.schema import SessionsResponse, SessionSummary
from agentdrops.repository.sessions import SessionStore
from agentdrops.types.response import SuccessResponse

router = APIRouter(prefix="/research", tags=["sessions"])


@router.get("/sessions", response_model=SuccessResponse[SessionsResponse])
async def list_sessions(request: Request) -> SuccessResponse[SessionsResponse]:
    """List every known research thread, most recently started first, for the sidebar."""
    sessions: SessionStore = request.app.state.sessions
    return SuccessResponse(
        data=SessionsResponse(
            sessions=[
                SessionSummary(
                    id=s.thread_id,
                    title=s.title,
                    created_at=s.created_at.isoformat(),
                    status=s.status,
                )
                for s in sessions.list_recent()
            ]
        )
    )
