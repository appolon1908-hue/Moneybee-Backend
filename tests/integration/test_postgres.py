from sqlalchemy import text

from app.core.database import engine


async def test_postgres_bootstrap_migration_is_applied() -> None:
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT to_regclass('public.platform_metadata')"))
    assert result.scalar_one() == "platform_metadata"
