from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.correlation import current_request_id


class MoneyBeeError(Exception):
    def __init__(
        self,
        *,
        code: str,
        title: str,
        detail: str,
        status_code: int,
        retryable: bool = False,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.title = title
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        self.context = context or {}
        super().__init__(detail)


def error_body(
    *,
    code: str,
    title: str,
    detail: str,
    retryable: bool,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "title": title,
            "detail": detail,
            "request_id": current_request_id(),
            "retryable": retryable,
            "context": context or {},
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(MoneyBeeError)
    async def moneybee_error_handler(
        request: Request,
        exc: MoneyBeeError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                code=exc.code,
                title=exc.title,
                detail=exc.detail,
                retryable=exc.retryable,
                context=exc.context,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                code="VALIDATION_ERROR",
                title="Request validation failed",
                detail="One or more request fields are invalid.",
                retryable=False,
                context={"errors": exc.errors()},
            ),
        )
