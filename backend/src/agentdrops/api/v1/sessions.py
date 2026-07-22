"""Session-listing endpoint: recent research threads for the sidebar."""

from fastapi import APIRouter, Request, status

from agentdrops.api.v1.schema import SessionsResponse
from agentdrops.service.sessions_service import SessionsService
from agentdrops.types.response import SuccessResponse

router = APIRouter(prefix="/research", tags=["sessions"])


@router.get(
    "/sessions",
    response_model=SuccessResponse[SessionsResponse],
    status_code=status.HTTP_200_OK,
    summary="List recent research sessions",
)
async def list_sessions(request: Request) -> SuccessResponse[SessionsResponse]:
    """List every known research thread, most recently started first, for the sidebar."""
    service: SessionsService = request.app.state.sessions_service
    return SuccessResponse(data=SessionsResponse(sessions=await service.list_recent()))
