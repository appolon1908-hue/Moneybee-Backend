from sqlalchemy import text

from app.core.database import AsyncSessionLocal


async def test_postgresql_connection() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.scalar(text("SELECT 1"))
    assert result == 1
