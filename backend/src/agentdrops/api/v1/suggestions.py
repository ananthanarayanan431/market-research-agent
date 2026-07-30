"""Starter-suggestion endpoint: LLM-generated example research prompts for the idle chat state."""

from fastapi import APIRouter, Request, status

from agentdrops.api.v1.schema import StarterSuggestionsResponse
from agentdrops.service.suggestions_service import SuggestionsService
from agentdrops.types.response import SuccessResponse

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


@router.get(
    "/starter",
    response_model=SuccessResponse[StarterSuggestionsResponse],
    status_code=status.HTTP_200_OK,
    summary="Get example research prompts for the idle chat state",
)
async def get_starter_suggestions(
    request: Request,
) -> SuccessResponse[StarterSuggestionsResponse]:
    """LLM-generated example prompts shown before the user has typed anything, cached for an
    hour so this isn't a fresh LLM call on every page load."""
    service: SuggestionsService = request.app.state.suggestions_service
    prompts = await service.get_starter_prompts()
    return SuccessResponse(data=StarterSuggestionsResponse(prompts=prompts))
