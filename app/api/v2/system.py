from fastapi import APIRouter
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine
from app.core.redis import redis_client

router = APIRouter()

@router.get("/version")
async def version() -> dict[str, str]:
    return {"application": "moneybee-api", "version": settings.app_version, "git_sha": settings.git_sha, "migration_head": settings.migration_head}

@router.get("/readiness")
async def readiness() -> dict[str, object]:
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "unavailable"
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    ready = all(v == "ok" for v in checks.values())
    return {"status": "ready" if ready else "not_ready", "checks": checks, "capabilities": settings.capabilities()}
