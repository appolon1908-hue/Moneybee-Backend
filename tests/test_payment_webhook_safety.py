import hashlib
import hmac
import json
import os
import time
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.config import settings
from app.db import SessionLocal
from app.integration_models import IntegrationInboxMessage
from app.main import app


def _stripe_signature(body: bytes, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


async def test_payment_webhook_retains_only_minimized_operational_fields(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_minimized")
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = {
        "id": event_id,
        "type": "payment_intent.succeeded",
        "created": int(time.time()),
        "livemode": False,
        "data": {
            "object": {
                "id": f"pi_{uuid.uuid4().hex}",
                "object": "payment_intent",
                "status": "succeeded",
                "amount": 12500,
                "currency": "usd",
                "customer_email": "private-customer@example.com",
                "billing_details": {
                    "name": "Private Customer",
                    "email": "private-customer@example.com",
                    "phone": "+15555550123",
                    "address": {"line1": "123 Private Street"},
                },
                "payment_method": {
                    "card": {"last4": "4242", "fingerprint": "secret-fingerprint"}
                },
                "metadata": {
                    "application_id": "application-safe-reference",
                    "private_note": "must-not-be-retained",
                },
            }
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = _stripe_signature(body, "whsec_minimized", int(time.time()))

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
        )

    assert response.status_code == 202
    async with SessionLocal() as db:
        inbox = await db.scalar(
            select(IntegrationInboxMessage).where(
                IntegrationInboxMessage.provider == "stripe",
                IntegrationInboxMessage.event_id == event_id,
            )
        )
        receipt = await db.scalar(
            select(models.WebhookReceipt).where(
                models.WebhookReceipt.provider == "stripe",
                models.WebhookReceipt.provider_event_id == event_id,
            )
        )
        assert inbox is not None
        assert receipt is not None
        stored = json.dumps(inbox.payload, sort_keys=True)
        assert "private-customer@example.com" not in stored
        assert "Private Customer" not in stored
        assert "123 Private Street" not in stored
        assert "4242" not in stored
        assert "secret-fingerprint" not in stored
        assert "must-not-be-retained" not in stored
        assert inbox.payload["linkage"] == {
            "application_id": "application-safe-reference"
        }
        assert inbox.payload["object"]["amount"] == 12500
        assert receipt.payload_hash == hashlib.sha256(body).hexdigest()
        assert receipt.payload_metadata["raw_payload_stored"] is False
        assert receipt.payload_metadata["payload_storage"] == "minimized"


def test_same_payment_event_id_with_changed_signed_content_conflicts(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_conflict")
    event_id = f"evt_{uuid.uuid4().hex}"
    first_body = json.dumps(
        {"id": event_id, "type": "transfer.paid", "data": {"object": {"id": "tr_1"}}},
        separators=(",", ":"),
    ).encode()
    changed_body = json.dumps(
        {"id": event_id, "type": "transfer.failed", "data": {"object": {"id": "tr_1"}}},
        separators=(",", ":"),
    ).encode()

    with TestClient(app) as client:
        first = client.post(
            "/api/v2/webhooks/stripe",
            content=first_body,
            headers={
                "Stripe-Signature": _stripe_signature(
                    first_body, "whsec_conflict", int(time.time())
                )
            },
        )
        conflict = client.post(
            "/api/v2/webhooks/stripe",
            content=changed_body,
            headers={
                "Stripe-Signature": _stripe_signature(
                    changed_body, "whsec_conflict", int(time.time())
                )
            },
        )

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.headers["content-type"].startswith("application/problem+json")
    assert conflict.json()["code"] == "WEBHOOK_EVENT_ID_CONFLICT"
