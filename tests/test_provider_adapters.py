import os
import uuid
import hashlib
import hmac

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.config import settings
from app.integrations.registry import provider_statuses
from app.integration_routes import verify_codestra_signature
from app.integrations.mapping import get_path, map_payload
from app.integrations.middesk import MiddeskAdapter
from app.integrations.middleware import canonical_event_type
from app.main import app
from app.notification_policy import channels_for_event


def test_provider_registry_is_disabled_and_secret_free_by_default():
    statuses = provider_statuses()

    assert statuses
    assert all(row.selected is False for row in statuses)
    assert all(row.configured is False for row in statuses)
    assert settings.bank_provider == "disabled"
    assert settings.email_provider == "disabled"
    assert settings.sms_provider == "disabled"
    assert settings.object_storage_mode == "disabled"
    assert settings.middleware_provider == "disabled"
    assert settings.crm_provider == "disabled"


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


def test_integration_event_names_are_versioned():
    assert canonical_event_type("LeadSubmitted") == "lead.created.v1"
    assert canonical_event_type("FundingConfirmed") == "funding_confirmed.v1"
    assert canonical_event_type("offer.accepted.v1") == "offer.accepted.v1"


def test_codestra_signature_is_fail_closed_and_constant_time_compatible():
    body = b'{"event_id":"evt-1"}'
    secret = "test-secret"
    timestamp = "1700000000"
    signed_payload = timestamp.encode() + b"." + body
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()

    assert verify_codestra_signature(
        body, f"sha256={signature}", secret, timestamp, now=1700000000
    )
    assert not verify_codestra_signature(body, None, secret, timestamp, now=1700000000)
    assert not verify_codestra_signature(
        body + b"x", signature, secret, timestamp, now=1700000000
    )
    assert not verify_codestra_signature(
        body, signature, secret, timestamp, now=1700001000
    )


def test_provider_mapping_only_uses_declared_paths():
    source = {"business": {"name": "MoneyBee"}, "owners": [{"name": "A"}]}

    assert get_path(source, "owners.0.name") == "A"
    assert map_payload(source, {"company.legalName": "business.name"}) == {
        "company": {"legalName": "MoneyBee"}
    }


def test_notification_policy_respects_preference_readiness_and_quiet_hours():
    channels = channels_for_event(
        "offer.received.v1",
        in_app_enabled=True,
        email_enabled=True,
        sms_enabled=True,
        marketing_consent=False,
        ready_channels=frozenset({"in_app", "email", "sms"}),
        quiet_hours=True,
    )

    assert channels == frozenset({"in_app", "email"})


def test_middesk_normalization_and_signature(monkeypatch):
    adapter = MiddeskAdapter()
    normalized = adapter.normalize(
        {"id": "business-1", "status": "in_review", "watchlist": {"hits": [1]}}
    )
    body = b'{"id":"event-1"}'
    secret = "middesk-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(settings, "middesk_webhook_secret", secret)

    assert normalized["status"] == "REVIEW_REQUIRED"
    assert normalized["normalized_result"]["risk_flags"] == ["WATCHLIST_HIT"]
    assert adapter.verify_webhook(body, signature)
