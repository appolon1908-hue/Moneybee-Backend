import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def test_api_v2_is_canonical_with_v1_compatibility():
    with TestClient(app) as client:
        canonical = client.get("/api/v2/me")
        compatibility = client.get("/api/v1/me")
        openapi = client.get("/openapi.json").json()

    assert canonical.status_code == 200
    assert compatibility.status_code == 200
    assert compatibility.headers["Deprecation"] == "true"
    assert "Sunset" in compatibility.headers
    assert 'rel="successor-version"' in compatibility.headers["Link"]
    assert "/api/v2/me" in openapi["paths"]
    assert "/api/v1/me" not in openapi["paths"]


def test_public_prequalification_requires_idempotency_key_before_processing():
    with TestClient(app) as client:
        response = client.post("/api/v2/public/prequalifications", json={})

    assert response.status_code == 428
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["type"].endswith("/idempotency-required")


def test_capabilities_fail_closed_when_environment_has_no_flags():
    with TestClient(app) as client:
        response = client.get("/api/v2/me/capabilities")

    assert response.status_code == 200
    assert response.json() == {}
