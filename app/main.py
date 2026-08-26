from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import identity_models, integration_models, models, portal_models
from app.config import settings
from app.db import engine
from app.integration_routes import router as integration_router
from app.portal import router as portal_router
from app.routers import router
from app.schemas import ProblemDetail


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="2.0.0",
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
        "X-Organization-ID",
        "X-Request-ID",
    ],
)
app.include_router(router, prefix="/api/v2")
app.include_router(integration_router, prefix="/api/v2")
app.include_router(portal_router, prefix="/api/v2")
app.include_router(router, prefix="/api/v1", include_in_schema=False)
app.include_router(integration_router, prefix="/api/v1", include_in_schema=False)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    )
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if settings.app_env.lower() not in {"production", "prod"}:
        raise exc
    problem = ProblemDetail(
        type="https://moneybee.example/problems/internal-server-error",
        title="Internal Server Error",
        status=500,
        detail="The request could not be completed.",
        instance=str(request.url.path),
        code="INTERNAL_SERVER_ERROR",
    )
    return JSONResponse(status_code=500, content=problem.model_dump(mode="json"))


@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": "2.0.0",
        "environment": settings.app_env,
    }


@app.get("/ready", tags=["system"])
async def ready():
    return {
        "status": "ready",
        "capability_policy": {
            "credit_live_pull": settings.credit_live_pull,
            "lenders_live_submission": settings.lenders_live_submission,
            "esign_live_send": settings.esign_live_send,
        },
    }
