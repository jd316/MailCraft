"""Typed application errors + handlers producing the API error envelope."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.backend.core.logging import get_logger

log = get_logger("errors")


class AppError(Exception):
    code: str = "APP_ERROR"
    status_code: int = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationFailed(AppError):
    code = "VALIDATION_ERROR"
    status_code = 400


class NotFound(AppError):
    code = "NOT_FOUND"
    status_code = 404


class UpstreamError(AppError):
    code = "UPSTREAM_ERROR"
    status_code = 502


class GenerationTimeout(AppError):
    code = "GENERATION_TIMEOUT"
    status_code = 504


class RateLimited(AppError):
    code = "RATE_LIMITED"
    status_code = 429


def _envelope(code: str, message: str, request: Request, details: dict | None = None) -> dict:
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        }
    }
    if details:
        body["error"]["details"] = details
    return body


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    log.warning("app_error", code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(exc.code, exc.message, request, exc.details),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=_envelope(
            "VALIDATION_ERROR",
            "Request payload failed validation.",
            request,
            {"errors": exc.errors()},
        ),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code_map = {404: "NOT_FOUND", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 429: "RATE_LIMITED"}
    code = code_map.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, str(exc.detail), request),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", error=str(exc))
    return JSONResponse(
        status_code=500,
        content=_envelope("INTERNAL_ERROR", "Internal server error.", request),
    )
