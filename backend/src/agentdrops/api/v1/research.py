"""Research endpoints: thread status and completed reports (see `sessions.py` for listing)."""

from fastapi import APIRouter, Request, status

from agentdrops.api.v1.schema import ReportResponse, ResearchStatusResponse
from agentdrops.service.research_service import ResearchService
from agentdrops.types.error_codes import NotFoundError, fastAPIErrorResponseModels
from agentdrops.types.response import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/research", tags=["research"])


@router.get(
    "/{thread_id}",
    response_model=SuccessResponse[ResearchStatusResponse],
    status_code=status.HTTP_200_OK,
    summary="Get research thread status",
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def get_research_status(
    request: Request, thread_id: str
) -> SuccessResponse[ResearchStatusResponse]:
    """Read one thread's current status; 404 if `thread_id` is unknown."""
    service: ResearchService = request.app.state.research_service
    result = await service.get_status(thread_id)
    if result is None:
        raise ErrorResponse(NotFoundError(message="Unknown thread_id"))
    return SuccessResponse(data=result)


@router.get(
    "/{thread_id}/report",
    response_model=SuccessResponse[ReportResponse],
    status_code=status.HTTP_200_OK,
    summary="Get a completed research report",
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def get_research_report(request: Request, thread_id: str) -> SuccessResponse[ReportResponse]:
    """Fetch a completed thread's report and sources, so the drawer can reopen without a rerun."""
    service: ResearchService = request.app.state.research_service
    result = await service.get_report(thread_id)
    if result is None:
        raise ErrorResponse(NotFoundError(message="Report not available for this thread_id"))
    return SuccessResponse(data=result)
