from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_version_endpoint() -> None:
    response = client.get("/api/v2/system/version")
    assert response.status_code == 200
    body = response.json()
    assert body["application"] == "moneybee-api"
    assert "git_sha" in body
