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


def test_metrics_exposes_prometheus_text():
    with TestClient(app) as client:
        client.get("/health/live")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "moneybee_http_requests_in_flight" in body
    assert "moneybee_http_requests_total" in body
    assert 'route="/health/live"' in body
    assert 'status_class="2xx"' in body
    assert "moneybee_http_request_duration_seconds_bucket" in body
