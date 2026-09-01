import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def test_me_permissions_returns_effective_local_authorization():
    with TestClient(app) as client:
        response = client.get("/api/v2/me/permissions")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "active_organization_id",
        "roles",
        "permissions",
        "membership_types",
    }
    assert isinstance(payload["roles"], list)
    assert isinstance(payload["permissions"], list)
    assert isinstance(payload["membership_types"], list)


def test_public_products_fails_closed_to_empty_catalog_without_active_programs():
    with TestClient(app) as client:
        response = client.get("/api/v2/public/products")

    assert response.status_code == 200
    assert response.json() == []


def test_contract_completion_routes_are_v2_canonical_with_hidden_v1_aliases():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()
        compatibility_permissions = client.get("/api/v1/me/permissions")
        compatibility_products = client.get("/api/v1/public/products")

    assert "/api/v2/me/permissions" in openapi["paths"]
    assert "/api/v2/public/products" in openapi["paths"]
    assert "/api/v1/me/permissions" not in openapi["paths"]
    assert "/api/v1/public/products" not in openapi["paths"]
    assert compatibility_permissions.status_code == 200
    assert compatibility_products.status_code == 200
