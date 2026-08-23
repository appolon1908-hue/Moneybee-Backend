from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.redis import redis_client


router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> dict[str, object] | JSONResponse:
    database_ok = False
    redis_ok = False

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False

    try:
        redis_ok = bool(await redis_client.ping())
    except Exception:
        redis_ok = False

    payload: dict[str, object] = {
        "status": "ready" if database_ok and redis_ok else "not_ready",
        "dependencies": {
            "postgresql": database_ok,
            "redis": redis_ok,
        },
    }

    if not database_ok or not redis_ok:
        return JSONResponse(status_code=503, content=payload)

    return payload
