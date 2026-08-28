import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import financial_models, identity_models, models  # noqa: F401
from app.portal import models as portal_models  # noqa: F401
from app.account_routes import router as account_router
from app.config import settings
from app.db import SessionLocal, engine, initialize_local_schema
from app.financial_routes import router as financial_router
from app.integration_routes import router as integration_router
from app.portal import router as portal_router
from app.routers import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_local_schema()
    try:
        yield
    finally:
        if settings.app_env == "test":
            await engine.dispose()


app = FastAPI(
    title="MoneyBeeLoans API",
    version="0.5.0",
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
        "traceparent",
        "X-Correlation-ID",
        "X-Request-ID",
        "X-Organization-ID",
    ],
)
app.include_router(router, prefix="/api/v2")
app.include_router(account_router, prefix="/api/v2")
app.include_router(integration_router, prefix="/api/v2")
app.include_router(portal_router, prefix="/api/v2")
app.include_router(financial_router, prefix="/api/v2")
app.include_router(router, prefix="/api/v1", include_in_schema=False)
app.include_router(integration_router, prefix="/api/v1", include_in_schema=False)
app.include_router(portal_router, prefix="/api/v1", include_in_schema=False)
app.include_router(financial_router, prefix="/api/v1", include_in_schema=False)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    correlation_id = request.headers.get("X-Correlation-ID") or request_id

    if (
        request.method == "POST"
        and request.url.path in {
            "/api/v1/public/prequalifications",
            "/api/v2/public/prequalifications",
        }
        and not request.headers.get("Idempotency-Key")
    ):
        return JSONResponse(
            status_code=428,
            media_type="application/problem+json",
            content={
                "type": "https://api.moneybeeloan.com/problems/idempotency-required",
                "title": "Idempotency key required",
                "status": 428,
                "detail": "Idempotency-Key is required for public prequalification submissions.",
                "instance": request.url.path,
                "request_id": request_id,
                "correlation_id": correlation_id,
            },
            headers={
                "X-Request-ID": request_id,
                "X-Correlation-ID": correlation_id,
                "Cache-Control": "no-store",
            },
        )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith("/api/v1/"):
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = "Thu, 31 Dec 2026 23:59:59 GMT"
        response.headers["Link"] = '</api/v2>; rel="successor-version"'
    return response


@app.exception_handler(RequestValidationError)
async def validation_problem(request: Request, exc: RequestValidationError):
    request_id = request.headers.get("X-Request-ID")
    correlation_id = request.headers.get("X-Correlation-ID") or request_id
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
            "request_id": request_id,
            "correlation_id": correlation_id,
        },
    )


@app.get("/health/live", tags=["health"])
async def live():
    return {"status": "ok", "environment": settings.app_env}


@app.get("/health/ready", tags=["health"])
async def ready():
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "ready", "environment": settings.app_env}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "environment": settings.app_env},
        )
