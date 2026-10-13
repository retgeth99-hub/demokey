from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        title: str,
        detail: str,
        *,
        retryable: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        self.retryable = retryable
        self.extra = extra or {}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        body = {
            "type": f"https://demo.local/problems/{exc.code.lower().replace('_', '-')}",
            "title": exc.title,
            "status": exc.status_code,
            "code": exc.code,
            "detail": exc.detail,
            "retryable": exc.retryable,
            "correlation_id": correlation_id,
            **exc.extra,
        }
        return JSONResponse(body, status_code=exc.status_code, media_type="application/problem+json")

