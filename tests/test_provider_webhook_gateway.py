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
from app.main import app
from app.portal.webhooks import verify_provider_signature


def signature(body: bytes, timestamp: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def test_provider_signature_rejects_missing_stale_and_invalid_values():
    body = b'{"id":"evt-1"}'
    secret = "test-secret"
    now = 1_700_000_000
    timestamp = str(now)
    valid = signature(body, timestamp, secret)
    assert verify_provider_signature(
        body, valid, timestamp, secret, tolerance_seconds=300, now=now
    )
    assert not verify_provider_signature(
        body, valid, str(now - 301), secret, tolerance_seconds=300, now=now
    )
    assert not verify_provider_signature(
        body, "sha256=bad", timestamp, secret, tolerance_seconds=300, now=now
    )


def test_provider_webhook_is_authenticated_deduplicated_and_conflict_safe(monkeypatch):
    secret = "gateway-test-secret"
    monkeypatch.setattr(settings, "provider_webhook_allowlist_csv", "lender-test")
    monkeypatch.setattr(
        settings, "provider_webhook_secrets_json", json.dumps({"lender-test": secret})
    )
    body = json.dumps(
        {
            "event_id": "evt-portal-1",
            "event_type": "submission.status_changed",
            "application_id": "app-1",
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-MoneyBee-Timestamp": timestamp,
        "X-MoneyBee-Signature": signature(body, timestamp, secret),
        "X-Provider-Event-ID": "evt-portal-1",
    }
    with TestClient(app) as client:
        first = client.post(
            "/api/v2/webhooks/providers/lender-test", content=body, headers=headers
        )
        duplicate = client.post(
            "/api/v2/webhooks/providers/lender-test", content=body, headers=headers
        )
        changed = b'{"event_id":"evt-portal-1","event_type":"different"}'
        changed_headers = {
            **headers,
            "X-MoneyBee-Signature": signature(changed, timestamp, secret),
        }
        conflict = client.post(
            "/api/v2/webhooks/providers/lender-test",
            content=changed,
            headers=changed_headers,
        )
        receipts = client.get("/api/v2/admin/webhook-receipts?provider=lender-test")

    assert first.status_code == 202
    assert first.json()["duplicate"] is False
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "WEBHOOK_EVENT_ID_CONFLICT"
    assert receipts.status_code == 200
    assert len(receipts.json()) == 1
