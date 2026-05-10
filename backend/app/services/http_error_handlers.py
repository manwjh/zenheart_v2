from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.ws_errors import http_error_body


def register_http_error_handlers(app: Any) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        del request
        code = _code_from_detail(exc.detail, fallback=_code_from_status(exc.status_code))
        return JSONResponse(
            status_code=exc.status_code,
            content=http_error_body(code, detail=exc.detail),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content=http_error_body(
                "invalid_request_payload",
                detail=exc.errors(),
                message="The HTTP request payload is invalid.",
                hint="Check the request body, query parameters, and required fields.",
                retryable=False,
            ),
        )


def _code_from_detail(detail: Any, *, fallback: str) -> str:
    if isinstance(detail, dict):
        for key in ("code", "reason", "error"):
            value = detail.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(detail, str):
        candidate = detail.strip()
        if (
            candidate
            and candidate == candidate.lower()
            and all(ch.isalnum() or ch == "_" for ch in candidate)
        ):
            return candidate[:80]
    return fallback


def _code_from_status(status_code: int) -> str:
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "invalid_request_payload"
    if status_code == 429:
        return "rate_limit_exceeded"
    if status_code >= 500:
        return "internal_error"
    return f"http_{status_code}"
