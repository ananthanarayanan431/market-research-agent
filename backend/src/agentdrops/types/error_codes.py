"""Typed error payloads, one class per HTTP status this API returns deliberately."""

from typing import Any

from fastapi import status
from pydantic import BaseModel, Field


class Error(BaseModel):
    code: int = Field(..., description="Error code")
    description: str = Field(..., description="Error description")
    message: str | None = Field(default=None, description="Custom Error message")


class NotFoundError(Error):
    code: int = status.HTTP_404_NOT_FOUND
    description: str = "Not found"


class BadRequestError(Error):
    code: int = status.HTTP_400_BAD_REQUEST
    description: str = "Bad Request"


class EnityConflictError(Error):
    code: int = status.HTTP_409_CONFLICT
    description: str = "An entity conflict occurred"


class UnauthorizedError(Error):
    code: int = status.HTTP_401_UNAUTHORIZED
    description: str = "Unauthorized"


class BadGatewayError(Error):
    code: int = status.HTTP_502_BAD_GATEWAY
    description: str = "Upstream dependency failed"


class ValidationError(Error):
    code: int = status.HTTP_422_UNPROCESSABLE_CONTENT
    description: str = "Validation Error"


fastAPIErrorResponseModels: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {"model": BadRequestError},
    status.HTTP_401_UNAUTHORIZED: {"model": UnauthorizedError},
    status.HTTP_404_NOT_FOUND: {"model": NotFoundError},
    status.HTTP_409_CONFLICT: {"model": EnityConflictError},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ValidationError},
    status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": Error},
    status.HTTP_502_BAD_GATEWAY: {"model": BadGatewayError},
}
