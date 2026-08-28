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
from app import public_intake_models  # noqa: F401
from app.config import settings
from app.db import SessionLocal, engine, initialize_local_schema
from app.financial_routes import router as financial_router
from app.integration_routes import router as integration_router
from app.portal import router as portal_router
from app.public_intake_routes import router as public_intake_router
from app.rate_limit import check_request_rate_limit
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
app.include_router(router, prefix="/api/v2")
app.include_router(integration_router, prefix="/api/v2")
app.include_router(portal_router, prefix="/api/v2")
app.include_router(public_intake_router, prefix="/api/v2")
app.include_router(financial_router, prefix="/api/v2")
app.include_router(router, prefix="/api/v1", include_in_schema=False)
app.include_router(integration_router, prefix="/api/v1", include_in_schema=False)
app.include_router(portal_router, prefix="/api/v1", include_in_schema=False)
app.include_router(public_intake_router, prefix="/api/v1", include_in_schema=False)
app.include_router(financial_router, prefix="/api/v1", include_in_schema=False)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    rate_limit = check_request_rate_limit(request)
    if rate_limit and rate_limit.limited:
        return JSONResponse(
            status_code=429,
            media_type="application/problem+json",
            headers={
                "Retry-After": str(rate_limit.reset_seconds),
                "X-RateLimit-Limit": str(rate_limit.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(rate_limit.reset_seconds),
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "strict-origin-when-cross-origin",
            },
            content={
                "type": "https://api.moneybeeloan.com/problems/rate-limit",
                "title": "Rate limit exceeded",
                "status": 429,
                "detail": "Too many requests. Try again after the retry window.",
                "instance": request.url.path,
                "request_id": request_id,
            },
        )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if rate_limit:
        response.headers["X-RateLimit-Limit"] = str(rate_limit.limit)
        response.headers["X-RateLimit-Remaining"] = str(rate_limit.remaining)
        response.headers["X-RateLimit-Reset"] = str(rate_limit.reset_seconds)
    return response


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
