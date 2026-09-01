import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

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
