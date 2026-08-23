from fastapi.testclient import TestClient

from app.main import app


def test_api_v2_is_canonical_with_v1_compatibility():
    with TestClient(app) as client:
        canonical = client.get("/api/v2/me")
        compatibility = client.get("/api/v1/me")
        openapi = client.get("/openapi.json").json()

    assert canonical.status_code == 200
    assert compatibility.status_code == 200
    assert "/api/v2/me" in openapi["paths"]
    assert "/api/v1/me" not in openapi["paths"]


def test_capabilities_fail_closed_when_environment_has_no_flags():
    with TestClient(app) as client:
        response = client.get("/api/v2/me/capabilities")

    assert response.status_code == 200
    assert response.json() == {}
