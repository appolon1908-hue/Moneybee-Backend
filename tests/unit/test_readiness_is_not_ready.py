from fastapi.testclient import TestClient

from app.main import app


def test_bootstrap_readiness_remains_partial() -> None:
    client = TestClient(app)
    response = client.get("/api/v2/system/readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["FINAL_STATUS"] == "PARTIAL"
    assert body["OVERALL_SYSTEM_STATUS"] == "PARTIAL"
    assert body["PRODUCTION_FEATURES_ENABLED"] == []
