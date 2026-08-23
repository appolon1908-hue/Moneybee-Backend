import uuid

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import router
from app.config import get_settings
from app.database import SessionLocal
from app.schemas import HealthRead

settings = get_settings()
app = FastAPI(title="MoneyBee API", version="1.0.0", docs_url="/docs" if settings.environment != "production" else None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
)


@app.middleware("http")
async def correlation_id(request: Request, call_next):
    request.state.correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(Exception)
async def unexpected_error(request: Request, _exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "correlation_id": request.state.correlation_id},
    )


@app.get("/health/live", response_model=HealthRead)
async def live() -> HealthRead:
    return HealthRead(status="ok")


@app.get("/health/ready", response_model=HealthRead)
async def ready() -> HealthRead:
    database = "down"
    redis_status = "down"
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
        database = "ok"
    client = redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await client.ping()
        redis_status = "ok"
    finally:
        await client.aclose()
    return HealthRead(status="ok", database=database, redis=redis_status)


app.include_router(router, prefix=settings.api_prefix)
