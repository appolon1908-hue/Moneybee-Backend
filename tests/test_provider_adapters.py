import hashlib
import hmac
import json
import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.config import settings
from app import models
from app.integration_routes import verify_codestra_signature
from app.integrations.mapping import get_path, map_payload
from app.integrations.middleware import (
    MIDDLEWARE_CONTRACT,
    canonical_event_type,
    middleware_event_url,
    serialize_event_envelope,
    sign_outbound_event,
)
from app.integrations.middesk import MiddeskAdapter
from app.integrations.providers import DocuSignAdapter
from app.integrations.registry import provider_statuses
from app.main import app
from app.notification_policy import channels_for_event
from app.worker import external_delivery_enabled


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


def test_moneybee_database_stores_only_bank_credential_references():
    columns = set(models.BankProviderState.__table__.columns.keys())
    assert "credential_reference" in columns
    assert "access_token" not in columns
    assert "access_token_ciphertext" not in columns


async def test_docusign_envelope_creation_uses_stable_provider_idempotency(monkeypatch):
    captured = {}

    async def fake_request(**kwargs):
        captured.update(kwargs)
        return {"envelopeId": "envelope-1"}

    monkeypatch.setattr("app.integrations.providers.provider_request", fake_request)
    monkeypatch.setattr(settings, "docusign_account_id", "account")
    monkeypatch.setattr(settings, "docusign_access_token", "token")
    monkeypatch.setattr(settings, "docusign_template_id", "template")
    contract_id = str(uuid.uuid4())
    await DocuSignAdapter().send_envelope(
        contract_id=contract_id,
        signer_email="signer@example.invalid",
        signer_name="Signer",
    )
    assert captured["json"]["transactionId"] == contract_id


def test_banking_adapter_api_fails_closed_without_ready_capability():
    application_id = uuid.uuid4()

    with TestClient(app) as client:
        response = client.post(
            f"/api/v2/applications/{application_id}/bank/link-session"
        )
        adapters = client.get("/api/v2/admin/provider-adapters")

    assert response.status_code == 503
    assert response.json()["code"] == "CAPABILITY_UNAVAILABLE"
    assert adapters.status_code == 200
    assert all(row["configured"] is False for row in adapters.json())


def test_integration_event_names_are_versioned():
    assert canonical_event_type("LeadSubmitted") == "lead.created.v1"
    assert canonical_event_type("FundingConfirmed") == "funding_confirmed.v1"
    assert canonical_event_type("offer.accepted.v1") == "offer.accepted.v1"


def test_codestra_outbound_envelope_is_canonical_and_signed():
    envelope = {
        "schema_version": 1,
        "source": "moneybee",
        "contract": MIDDLEWARE_CONTRACT,
        "event_id": "event-1",
        "event_type": "public.contact_request.received.v1",
        "payload": {"reference": "MB-CONTACT-1", "amount": "10000.00"},
    }
    raw_body = serialize_event_envelope(envelope)
    timestamp = "1700000000"
    secret = "integration-signing-secret"
    expected_digest = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()

    assert raw_body == json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    assert sign_outbound_event(raw_body, timestamp, secret) == (
        f"sha256={expected_digest}"
    )
    assert middleware_event_url(
        "https://moneybee-events.codestra.co/",
        "/v1/events",
    ) == "https://moneybee-events.codestra.co/v1/events"


def test_external_delivery_gate_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("ENABLE_EXTERNAL_DELIVERY", raising=False)
    assert external_delivery_enabled() is False

    monkeypatch.setenv("ENABLE_EXTERNAL_DELIVERY", "true")
    assert external_delivery_enabled() is True

    monkeypatch.setenv("ENABLE_EXTERNAL_DELIVERY", "false")
    assert external_delivery_enabled() is False


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
