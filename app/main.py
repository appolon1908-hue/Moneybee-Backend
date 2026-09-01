import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import financial_models, identity_models, models  # noqa: F401
from app.portal import models as portal_models  # noqa: F401
from app import public_intake_models  # noqa: F401
from app.admin_routes import router as admin_router
from app.applications_routes import router as applications_router
from app.banking_routes import router as banking_router
from app.borrower_legacy_routes import router as borrower_legacy_router
from app.config import settings
from app.db import SessionLocal, engine, initialize_local_schema
from app.financial_routes import router as financial_router
from app.integration_routes import router as integration_router
from app.logging_config import Timer, bind_request_id, configure_logging, request_logger
from app.marketplace_routes import router as marketplace_router
from app.portal import router as portal_router
from app.public_intake_routes import router as public_intake_router
from app.rate_limit import InMemoryRateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await initialize_local_schema()
    try:
        yield
    finally:
        if settings.app_env == "test":
            await engine.dispose()


app = FastAPI(
    title="MoneyBeeLoans API",
    version="0.3.0",
    openapi_url="/openapi.json",
    docs_url="/docs" if settings.app_env != "production" else None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "If-Match",
        "X-Correlation-ID",
        "X-Request-ID",
        "X-Organization-ID",
    ],
)
app.include_router(applications_router, prefix="/api/v2")
app.include_router(marketplace_router, prefix="/api/v2")
app.include_router(admin_router, prefix="/api/v2")
app.include_router(borrower_legacy_router, prefix="/api/v2")
app.include_router(banking_router, prefix="/api/v2")
app.include_router(integration_router, prefix="/api/v2")
app.include_router(portal_router, prefix="/api/v2")
app.include_router(public_intake_router, prefix="/api/v2")
app.include_router(financial_router, prefix="/api/v2")
app.include_router(applications_router, prefix="/api/v1", include_in_schema=False)
app.include_router(marketplace_router, prefix="/api/v1", include_in_schema=False)
app.include_router(admin_router, prefix="/api/v1", include_in_schema=False)
app.include_router(borrower_legacy_router, prefix="/api/v1", include_in_schema=False)
app.include_router(banking_router, prefix="/api/v1", include_in_schema=False)
app.include_router(integration_router, prefix="/api/v1", include_in_schema=False)
app.include_router(portal_router, prefix="/api/v1", include_in_schema=False)
app.include_router(public_intake_router, prefix="/api/v1", include_in_schema=False)
app.include_router(financial_router, prefix="/api/v1", include_in_schema=False)
app.add_middleware(InMemoryRateLimitMiddleware)


def _api_v1_sunset_http_date() -> str:
    sunset_date = datetime.strptime(settings.api_v1_sunset_date, "%Y-%m-%d").replace(
        tzinfo=UTC
    )
    return format_datetime(sunset_date, usegmt=True)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    correlation_id = request.headers.get("X-Correlation-ID", request_id)
    bind_request_id(request_id)
    timer = Timer()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith("/api/v1/"):
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = _api_v1_sunset_http_date()
        response.headers["Link"] = (
            f'<{request.url.path.replace("/api/v1/", "/api/v2/", 1)}>; rel="successor-version"'
        )
    request_logger().info(
        "request.completed",
        extra={
            "http_method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": timer.elapsed_ms(),
        },
    )
    return response


_STATUS_TITLES: dict[int, str] = {
    400: "Bad request",
    401: "Authentication required",
    403: "Access denied",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    422: "Unprocessable entity",
    428: "Precondition required",
    429: "Too many requests",
}
_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "ACCESS_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "UNPROCESSABLE_ENTITY",
    428: "PRECONDITION_REQUIRED",
    429: "RATE_LIMITED",
}


def _slug(code: str) -> str:
    return code.lower().replace("_", "-")


async def http_exception_problem(request: Request, exc: StarletteHTTPException):
    """Every HTTPException in this codebase - whichever of the ad hoc detail
    shapes it was raised with ({"code","message"}, {"code","from_status",...},
    or a bare string) - converges here into one RFC 7807 envelope. The
    original detail's non-message keys (from_status/to_status/allowed, etc.)
    move to a "context" extension member rather than being dropped, since
    packages/api-client/src/core.ts on the frontend already reads
    problem.code and problem.context (built defensively ahead of this
    convergence landing)."""
    detail = exc.detail
    code: str
    message: str | None
    context: dict | None
    if isinstance(detail, dict):
        code = str(detail.get("code") or _STATUS_CODES.get(exc.status_code, "REQUEST_FAILED"))
        message = detail.get("message")
        context = {
            key: value for key, value in detail.items() if key not in {"code", "message"}
        } or None
    else:
        code = _STATUS_CODES.get(exc.status_code, "REQUEST_FAILED")
        message = str(detail) if detail else None
        context = None

    return JSONResponse(
        status_code=exc.status_code,
        media_type="application/problem+json",
        headers=exc.headers,
        content={
            "type": f"https://api.moneybeeloan.com/problems/{_slug(code)}",
            "title": _STATUS_TITLES.get(exc.status_code, "Request failed"),
            "status": exc.status_code,
            "detail": message or "The request could not be completed.",
            "instance": request.url.path,
            "request_id": request.headers.get("X-Request-ID"),
            "code": code,
            **({"context": context} if context else {}),
        },
    )


app.add_exception_handler(StarletteHTTPException, http_exception_problem)
app.add_exception_handler(HTTPException, http_exception_problem)


@app.exception_handler(RequestValidationError)
async def validation_problem(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "https://api.moneybeeloan.com/problems/validation",
            "title": "Request validation failed",
            "status": 422,
            "detail": "One or more fields are invalid.",
            "instance": request.url.path,
            "errors": jsonable_encoder(
                exc.errors(),
                custom_encoder={ValueError: str, Exception: str},
            ),
            "request_id": request.headers.get("X-Request-ID"),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_problem(request: Request, exc: Exception):
    request_id = request.headers.get("X-Request-ID")
    request_logger().exception(
        "request.unhandled_exception",
        extra={
            "http_method": request.method,
            "path": request.url.path,
            "request_id": request_id,
        },
    )
    return JSONResponse(
        status_code=500,
        media_type="application/problem+json",
        content={
            "type": "https://api.moneybeeloan.com/problems/internal-error",
            "title": "Internal server error",
            "status": 500,
            "detail": "An unexpected error occurred.",
            "instance": request.url.path,
            "request_id": request_id,
        },
    )


@app.get("/health/live", tags=["health"])
async def live():
    return {"status": "ok", "environment": settings.app_env}


def _expected_migration_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head()


@app.get("/health/ready", tags=["health"])
async def ready():
    checks: dict[str, str] = {}
    healthy = True

    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unreachable"
        healthy = False

    if healthy and not settings.auto_create_schema:
        try:
            expected_head = _expected_migration_head()
            async with SessionLocal() as db:
                result = await db.execute(text("SELECT version_num FROM alembic_version"))
                row = result.first()
            current_head = row[0] if row else None
            if current_head != expected_head:
                checks["migrations"] = f"drifted: db={current_head!r} code={expected_head!r}"
                healthy = False
            else:
                checks["migrations"] = "ok"
        except Exception as exc:
            checks["migrations"] = f"unreadable: {exc.__class__.__name__}"
            healthy = False
    else:
        checks["migrations"] = "skipped (auto_create_schema)"

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if healthy else "not_ready",
            "environment": settings.app_env,
            "checks": checks,
        },
    )
