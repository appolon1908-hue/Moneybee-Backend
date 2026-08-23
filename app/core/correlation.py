import uuid
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


request_id_context: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)

correlation_id_context: ContextVar[str | None] = ContextVar(
    "correlation_id",
    default=None,
)


def current_request_id() -> str | None:
    return request_id_context.get()


def current_correlation_id() -> str | None:
    return correlation_id_context.get()


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        correlation_id = request.headers.get("X-Correlation-ID") or request_id
        request_token = request_id_context.set(request_id)
        correlation_token = correlation_id_context.set(correlation_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            request_id_context.reset(request_token)
            correlation_id_context.reset(correlation_token)
