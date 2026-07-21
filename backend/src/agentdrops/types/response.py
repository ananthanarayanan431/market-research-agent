"""Generic success/error envelope every endpoint returns, so the frontend can branch on
`success` alone instead of guessing a response's shape from its status code."""

from pydantic import BaseModel, Field

from .error_codes import Error


class Response[DataT](BaseModel):
    success: bool = Field(..., description="Success status of the response")
    data: DataT | None = Field(None, description="Data to return in the response of type T")


class SuccessResponse[DataT](Response[DataT]):
    success: bool = True
    data: DataT = Field(..., description="Data to return in the response of type T")


class ErrorResponse(Exception):
    """Raise from a route or dependency; `handle_error_response` turns it into a JSON body."""

    def __init__(self, error: Error) -> None:
        super().__init__(error.message)
        self.error = error

    def __str__(self) -> str:
        return f"[Error {self.error.code}]: {self.error.description}"
