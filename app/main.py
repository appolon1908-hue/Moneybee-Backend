from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.v2.health import router as health_router
from app.api.v2.router import router as api_v2_router
from app.core.config import settings
from app.core.correlation import CorrelationMiddleware


app = FastAPI(
    title="MoneyBeeLoans API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    openapi_url="/openapi.json",
)

app.add_middleware(CorrelationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "If-Match",
        "X-Request-ID",
        "X-Correlation-ID",
    ],
)

install_error_handlers(app)
app.include_router(health_router)
app.include_router(api_v2_router, prefix="/api/v2")
