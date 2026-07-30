"""Session-management endpoints: list/search, rename/pin, and delete for the sidebar."""

from fastapi import APIRouter, Request, status

from agentdrops.api.v1.schema import SessionsResponse, SessionSummary, UpdateSessionRequest
from agentdrops.service.sessions_service import SessionsService
from agentdrops.types.error_codes import NotFoundError, fastAPIErrorResponseModels
from agentdrops.types.response import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/research", tags=["sessions"])


@router.get(
    "/sessions",
    response_model=SuccessResponse[SessionsResponse],
    status_code=status.HTTP_200_OK,
    summary="List recent research sessions",
)
async def list_sessions(
    request: Request, q: str | None = None
) -> SuccessResponse[SessionsResponse]:
    """List known research threads, pinned first then most recently started. `q` filters by
    title (case-insensitive substring) for the sidebar's search box."""
    service: SessionsService = request.app.state.sessions_service
    return SuccessResponse(data=SessionsResponse(sessions=await service.list_recent(q)))


@router.patch(
    "/sessions/{thread_id}",
    response_model=SuccessResponse[SessionSummary],
    status_code=status.HTTP_200_OK,
    summary="Rename and/or pin a research session",
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def update_session(
    request: Request, thread_id: str, body: UpdateSessionRequest
) -> SuccessResponse[SessionSummary]:
    """Rename a session, pin/unpin it, or both in one call; 404 if `thread_id` is unknown."""
    service: SessionsService = request.app.state.sessions_service
    result = await service.update(thread_id, title=body.title, pinned=body.pinned)
    if result is None:
        raise ErrorResponse(NotFoundError(message="Unknown thread_id"))
    return SuccessResponse(data=result)


@router.delete(
    "/sessions/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a research session",
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def delete_session(request: Request, thread_id: str) -> None:
    """Permanently delete a session's sidebar record; 404 if `thread_id` is unknown."""
    service: SessionsService = request.app.state.sessions_service
    if not await service.delete(thread_id):
        raise ErrorResponse(NotFoundError(message="Unknown thread_id"))
