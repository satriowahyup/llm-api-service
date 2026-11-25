"""Global FastAPI exception handlers returning a standardized JSON error envelope."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from llm_api_service.core.exceptions import AppError
from llm_api_service.core.logging import request_id_ctx

logger = logging.getLogger(__name__)


def _error_payload(
    *,
    code: str,
    message: str,
    details: Any | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id_ctx.get(),
    }
    if details:
        body["details"] = details
    return {"error": body}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach domain, validation, and fallback exception handlers to the FastAPI app."""

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "Handled domain error",
            extra={"error_code": exc.code, "status_code": exc.status_code},
        )
        headers: dict[str, str] = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(int(max(1, round(exc.retry_after))))
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code=exc.code, message=exc.message, details=exc.details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                code="validation_error",
                message="Request validation failed.",
                details=exc.errors(),
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                code="internal_error",
                message="An unexpected internal server error occurred.",
            ),
        )
