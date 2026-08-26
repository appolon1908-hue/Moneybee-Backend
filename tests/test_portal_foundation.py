import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def test_portal_identity_context_and_navigation_are_canonical():
    with TestClient(app) as client:
        identity = client.get("/api/v2/auth/me")
        context = client.get("/api/v2/auth/context")
        navigation = client.get("/api/v2/portal/navigation")
        compatibility = client.get("/api/v1/auth/context")
        openapi = client.get("/openapi.json").json()

    assert identity.status_code == 200
    assert identity.json()["subject"] == "local-admin"
    assert context.status_code == 200
    assert context.json()["portal"] == "ADMIN"
    assert navigation.status_code == 200
    assert any(item["key"] == "dashboard" for item in navigation.json())
    assert compatibility.status_code == 200
    assert "/api/v2/auth/context" in openapi["paths"]
    assert "/api/v1/auth/context" not in openapi["paths"]
