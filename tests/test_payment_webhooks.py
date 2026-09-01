import hashlib
import hmac
import json
import os
import time

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.config import settings
from app.integrations.payments import PayPalAdapter
from app.main import app


def _stripe_signature(body: bytes, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_stripe_webhook_is_authenticated_and_deduplicated(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    body = json.dumps({"id": f"evt_{time.time_ns()}", "type": "transfer.reversed"}).encode()
    header = _stripe_signature(body, "whsec_test", int(time.time()))

    with TestClient(app) as client:
        first = client.post(
            "/api/v2/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": header, "Content-Type": "application/json"},
        )
        second = client.post(
            "/api/v2/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": header, "Content-Type": "application/json"},
        )
        forged = client.post(
            "/api/v2/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": "t=1,v1=bad", "Content-Type": "application/json"},
        )

    assert first.status_code == 202
    assert first.json()["duplicate"] is False
    assert second.status_code == 202
    assert second.json()["duplicate"] is True
    assert forged.status_code == 401


def test_paypal_webhook_is_authenticated_and_deduplicated(monkeypatch):
    async def accept(self, body, headers):
        return True

    monkeypatch.setattr(PayPalAdapter, "verify_webhook", accept)
    body = json.dumps(
        {"id": f"WH-{time.time_ns()}", "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED"}
    ).encode()

    with TestClient(app) as client:
        first = client.post("/api/v2/webhooks/paypal", content=body)
        second = client.post("/api/v2/webhooks/paypal", content=body)

    assert first.status_code == 202
    assert first.json()["duplicate"] is False
    assert second.status_code == 202
    assert second.json()["duplicate"] is True


def test_paypal_webhook_rejects_an_invalid_signature(monkeypatch):
    async def deny(self, body, headers):
        return False

    monkeypatch.setattr(PayPalAdapter, "verify_webhook", deny)
    body = json.dumps(
        {"id": f"WH-{time.time_ns()}", "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED"}
    ).encode()

    with TestClient(app) as client:
        response = client.post("/api/v2/webhooks/paypal", content=body)

    assert response.status_code == 401
