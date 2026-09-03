import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal, engine
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
    monkeypatch.setattr("app.main._expected_migration_heads", lambda: ("0000_expected",))

    created_version_table = False
    if engine.dialect.name == "sqlite":
        async with SessionLocal() as db:
            await db.execute(
                text("CREATE TABLE IF NOT EXISTS alembic_version (version_num TEXT)")
            )
            await db.commit()
        created_version_table = True

    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert "drifted" in body["checks"]["migrations"]
        assert "0000_expected" in body["checks"]["migrations"]
    finally:
        if created_version_table:
            async with SessionLocal() as db:
                await db.execute(text("DROP TABLE alembic_version"))
                await db.commit()
