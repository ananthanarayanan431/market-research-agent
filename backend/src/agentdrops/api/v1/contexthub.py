"""Context Hub endpoints: upload files/URLs into the global knowledge base, list, and delete."""

from fastapi import APIRouter, Request, UploadFile, status

from agentdrops.api.v1.schema import (
    ContextHubDocumentResponse,
    ContextHubDocumentsResponse,
    ContextHubUrlRequest,
)
from agentdrops.repository.contexthub import ContextHubDocumentRecord
from agentdrops.service.contexthub_service import ContextHubService
from agentdrops.types.error_codes import (
    BadRequestError,
    NotFoundError,
    fastAPIErrorResponseModels,
)
from agentdrops.types.response import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/contexthub", tags=["contexthub"])

_EXTENSION_CONTENT_TYPE: dict[str, str] = {
    "pdf": "pdf",
    "docx": "docx",
    "txt": "txt",
    "csv": "csv",
}


def _resolve_content_type(filename: str | None) -> str | None:
    if not filename or "." not in filename:
        return None
    return _EXTENSION_CONTENT_TYPE.get(filename.rsplit(".", 1)[-1].lower())


def _to_response(document: ContextHubDocumentRecord) -> ContextHubDocumentResponse:
    return ContextHubDocumentResponse(
        id=document.id,
        title=document.title,
        source_type=document.source_type,  # type: ignore[arg-type]
        status=document.status,
        error=document.error,
        created_at=document.created_at.isoformat(),
    )


@router.post(
    "/documents",
    response_model=SuccessResponse[ContextHubDocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file into Context Hub",
    responses={
        status.HTTP_400_BAD_REQUEST: fastAPIErrorResponseModels[status.HTTP_400_BAD_REQUEST]
    },
)
async def upload_document(
    request: Request, file: UploadFile
) -> SuccessResponse[ContextHubDocumentResponse]:
    content_type = _resolve_content_type(file.filename)
    if content_type is None:
        raise ErrorResponse(
            BadRequestError(message="Unsupported file type — allowed: pdf, docx, txt, csv")
        )
    service: ContextHubService = request.app.state.contexthub_service
    data = await file.read()
    if len(data) > service.max_upload_mb * 1024 * 1024:
        raise ErrorResponse(
            BadRequestError(message=f"File exceeds the {service.max_upload_mb}MB upload limit")
        )
    document = await service.upload_file(file.filename or "upload", content_type, data)
    return SuccessResponse(data=_to_response(document))


@router.post(
    "/urls",
    response_model=SuccessResponse[ContextHubDocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Add a URL into Context Hub",
)
async def add_url(
    request: Request, body: ContextHubUrlRequest
) -> SuccessResponse[ContextHubDocumentResponse]:
    service: ContextHubService = request.app.state.contexthub_service
    document = await service.add_url(str(body.url))
    return SuccessResponse(data=_to_response(document))


@router.get(
    "/documents",
    response_model=SuccessResponse[ContextHubDocumentsResponse],
    summary="List Context Hub documents",
)
async def list_documents(request: Request) -> SuccessResponse[ContextHubDocumentsResponse]:
    service: ContextHubService = request.app.state.contexthub_service
    documents = await service.list_documents()
    return SuccessResponse(
        data=ContextHubDocumentsResponse(documents=[_to_response(d) for d in documents])
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a Context Hub document",
    responses={status.HTTP_404_NOT_FOUND: fastAPIErrorResponseModels[status.HTTP_404_NOT_FOUND]},
)
async def delete_document(request: Request, document_id: str) -> None:
    service: ContextHubService = request.app.state.contexthub_service
    result = await service.delete_document(document_id)
    if result == "not_found":
        raise ErrorResponse(NotFoundError(message="Unknown document_id"))
