from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_live_capabilities_default_off() -> None:
    from app.core.config import settings

    assert all(value is False for value in settings.capabilities().values())
