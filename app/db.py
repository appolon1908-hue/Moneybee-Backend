from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db_base import Base



_engine_options: dict[str, object] = {"pool_pre_ping": True}
if settings.app_env == "test":
    # Starlette TestClient creates a fresh event loop per context manager. A
    # pooled asyncpg connection cannot safely cross those loops, so tests use
    # unpooled connections while staging/production retain normal pooling.
    _engine_options["poolclass"] = NullPool

engine = create_async_engine(settings.database_url, **_engine_options)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def initialize_local_schema() -> None:
    if settings.auto_create_schema:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
