import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.config import settings
from app.integrations.registry import provider_statuses
from app.main import app


def test_provider_registry_is_disabled_and_secret_free_by_default():
    statuses = provider_statuses()

    assert statuses
    assert all(row.selected is False for row in statuses)
    assert all(row.configured is False for row in statuses)
    assert settings.bank_provider == "disabled"
    assert settings.email_provider == "disabled"
    assert settings.sms_provider == "disabled"
    assert settings.object_storage_mode == "disabled"


def test_banking_adapter_api_fails_closed_without_ready_capability():
    application_id = uuid.uuid4()

    with TestClient(app) as client:
        response = client.post(
            f"/api/v2/applications/{application_id}/bank/link-session"
        )
        adapters = client.get("/api/v2/admin/provider-adapters")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CAPABILITY_UNAVAILABLE"
    assert adapters.status_code == 200
    assert all(row["configured"] is False for row in adapters.json())
