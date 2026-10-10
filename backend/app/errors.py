"""The single error shape used by every endpoint.

Responses are always ``{"error": {"code", "message", "detail"}}`` so the
frontend can raise one ApiError against a stable shape. Each code maps to a
fixed HTTP status.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode:
    INVALID_PATH = "INVALID_PATH"
    INVALID_NAME = "INVALID_NAME"
    REPO_UNREACHABLE = "REPO_UNREACHABLE"
    NAME_TAKEN = "NAME_TAKEN"
    NOT_CLONED = "NOT_CLONED"
    DEPLOY_IN_PROGRESS = "DEPLOY_IN_PROGRESS"
    PROTECTED = "PROTECTED"
    NOT_FOUND = "NOT_FOUND"
    DOCKER_ERROR = "DOCKER_ERROR"
    GIT_ERROR = "GIT_ERROR"
    INVALID_STATE = "INVALID_STATE"


#: Fixed code -> HTTP status mapping.
CODE_STATUS: dict[str, int] = {
    ErrorCode.INVALID_PATH: status.HTTP_400_BAD_REQUEST,
    ErrorCode.INVALID_NAME: status.HTTP_400_BAD_REQUEST,
    ErrorCode.REPO_UNREACHABLE: status.HTTP_400_BAD_REQUEST,
    ErrorCode.NAME_TAKEN: status.HTTP_409_CONFLICT,
    ErrorCode.NOT_CLONED: status.HTTP_409_CONFLICT,
    ErrorCode.DEPLOY_IN_PROGRESS: status.HTTP_409_CONFLICT,
    ErrorCode.INVALID_STATE: status.HTTP_409_CONFLICT,
    ErrorCode.PROTECTED: status.HTTP_403_FORBIDDEN,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.DOCKER_ERROR: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.GIT_ERROR: status.HTTP_502_BAD_GATEWAY,
}


class ApiError(Exception):
    """Raised anywhere in the app; rendered as the standard envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}
        self.status_code = status_code or CODE_STATUS.get(code, status.HTTP_400_BAD_REQUEST)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "detail": self.detail,
            }
        }


def _envelope(
    code: str, message: str, detail: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=CODE_STATUS.get(code, status.HTTP_400_BAD_REQUEST),
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_payload(),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Surface the offending field so the client can highlight it.
        fields = [
            ".".join(str(part) for part in err.get("loc", ())[1:]) or "body"
            for err in exc.errors()
        ]
        return _envelope(
            ErrorCode.INVALID_NAME,
            "Request validation failed.",
            {"field": fields[0] if fields else "body", "fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return _envelope(ErrorCode.NOT_FOUND, "Resource not found.")
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return _envelope(ErrorCode.PROTECTED, str(exc.detail))
        return _envelope(ErrorCode.INVALID_STATE, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return the envelope. An unexpected failure should not
        # leak a traceback or break the frontend's error handling.
        logger.exception("Unhandled error", exc_info=exc)
        return _envelope(ErrorCode.DOCKER_ERROR, "Internal error.")