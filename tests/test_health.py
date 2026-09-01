import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.config import settings
from app.db import SessionLocal
from app.main import app


def test_liveness():
    with TestClient(app) as client:
        response = client.get(
            "/health/live",
            headers={
                "X-Request-ID": "test-request-id",
                "X-Correlation-ID": "test-correlation-id",
            },
        )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "test"}
    assert response.headers["X-Request-ID"] == "test-request-id"
    assert response.headers["X-Correlation-ID"] == "test-correlation-id"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_readiness_is_ok_when_the_database_is_reachable():
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    expected_migration_status = (
        "skipped (auto_create_schema)" if settings.auto_create_schema else "ok"
    )
    assert body["checks"]["migrations"] == expected_migration_status


async def test_readiness_flags_migration_head_drift(monkeypatch):
    monkeypatch.setattr(settings, "auto_create_schema", False)

    async with SessionLocal() as db:
        table_existed = await db.run_sync(
            lambda session: inspect(session.connection()).has_table("alembic_version")
        )
        original_heads: list[str] = []
        if table_existed:
            original_heads = list(
                (
                    await db.execute(text("SELECT version_num FROM alembic_version"))
                ).scalars()
            )
        else:
            await db.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL)")
            )
        await db.execute(text("DELETE FROM alembic_version"))
        await db.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('0000_stale_head')")
        )
        await db.commit()

    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert "drifted" in body["checks"]["migrations"]
        assert "0000_stale_head" in body["checks"]["migrations"]
    finally:
        async with SessionLocal() as db:
            if table_existed:
                await db.execute(text("DELETE FROM alembic_version"))
                for revision in original_heads:
                    await db.execute(
                        text(
                            "INSERT INTO alembic_version (version_num) VALUES (:revision)"
                        ),
                        {"revision": revision},
                    )
            else:
                await db.execute(text("DROP TABLE IF EXISTS alembic_version"))
            await db.commit()
