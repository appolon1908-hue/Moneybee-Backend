import hashlib
import hmac
import json
import time
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.rate_limit import reset_rate_limit_state


def _prequalification(unique: str) -> dict:
    return {
        "funding_amount": 75000,
        "currency": "USD",
        "use_of_funds": "WORKING_CAPITAL",
        "time_in_business_months": 24,
        "monthly_revenue": 50000,
        "business_name": "Rate Limited Honey Transport",
        "first_name": "Ralph",
        "last_name": "Appolon",
        "email": f"rate-{unique}@example.com",
        "phone": "+15555550123",
        "postal_code": "33101",
        "consents": [
            {
                "type": "APPLICATION_TERMS",
                "document_version": "v1",
                "accepted": True,
            }
        ],
        "marketing": {"landing_page": "business-loans"},
    }


def _signature(body: bytes, timestamp: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def test_public_intake_rate_limit_returns_problem_response(monkeypatch):
    reset_rate_limit_state()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "public_rate_limit_per_minute", 1)
    unique = uuid.uuid4().hex

    with TestClient(app) as client:
        first = client.post(
            "/api/v2/public/prequalifications",
            json=_prequalification(unique),
            headers={
                "Idempotency-Key": unique,
                "X-Forwarded-For": "203.0.113.10",
            },
        )
        limited = client.post(
            "/api/v2/public/prequalifications",
            json=_prequalification(uuid.uuid4().hex),
            headers={
                "Idempotency-Key": uuid.uuid4().hex,
                "X-Forwarded-For": "203.0.113.10",
            },
        )

    assert first.status_code == 202
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert limited.headers["X-RateLimit-Limit"] == "1"
    assert limited.json()["type"] == "https://api.moneybeeloan.com/problems/rate-limit"
    reset_rate_limit_state()


def test_webhook_rate_limit_applies_before_signature_work(monkeypatch):
    reset_rate_limit_state()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "webhook_rate_limit_per_minute", 1)
    monkeypatch.setattr(settings, "provider_webhook_allowlist_csv", "n8n")
    monkeypatch.setattr(settings, "provider_webhook_secrets_json", json.dumps({"n8n": "secret"}))
    body = b'{"event_id":"evt-rate-limit","event_type":"provider.changed"}'
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-MoneyBee-Timestamp": timestamp,
        "X-MoneyBee-Signature": _signature(body, timestamp, "secret"),
        "X-Forwarded-For": "203.0.113.20",
    }

    with TestClient(app) as client:
        first = client.post("/api/v2/webhooks/n8n", content=body, headers=headers)
        limited = client.post(
            "/api/v2/webhooks/n8n",
            content=b'{"event_id":"evt-rate-limit-2"}',
            headers={**headers, "X-MoneyBee-Signature": "sha256=bad"},
        )

    assert first.status_code == 202
    assert limited.status_code == 429
    assert limited.headers["X-RateLimit-Limit"] == "1"
    reset_rate_limit_state()


def test_rate_limit_does_not_apply_to_authenticated_business_routes(monkeypatch):
    reset_rate_limit_state()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "public_rate_limit_per_minute", 1)
    monkeypatch.setattr(settings, "webhook_rate_limit_per_minute", 1)

    with TestClient(app) as client:
        first = client.get(
            "/api/v2/me",
            headers={"Authorization": "Bearer local-test", "X-Forwarded-For": "203.0.113.30"},
        )
        second = client.get(
            "/api/v2/me",
            headers={"Authorization": "Bearer local-test", "X-Forwarded-For": "203.0.113.30"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "X-RateLimit-Limit" not in second.headers
    reset_rate_limit_state()
