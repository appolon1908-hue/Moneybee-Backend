from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import install_exception_handlers
from app.api.v2.router import router as v2_router
from app.api.v2.system import readiness
from app.core.config import settings
from app.core.correlation import CorrelationMiddleware
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield


app = FastAPI(title="MoneyBee API", version=settings.app_version, lifespan=lifespan)
app.add_middleware(CorrelationMiddleware)
install_exception_handlers(app)
app.include_router(v2_router, prefix="/api/v2")


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, object]:
    return await readiness()
