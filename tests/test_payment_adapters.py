import hashlib
import hmac
import json
import os
import time

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

import pytest

from app.config import settings
from app.integrations.base import ProviderError
from app.integrations.payments import PayPalAdapter, StripeAdapter
from app.integrations.registry import payment_adapter, provider_statuses


def _stripe_signature(body: bytes, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_payment_provider_is_disabled_by_default():
    statuses = {row.provider_type: row for row in provider_statuses()}
    assert statuses["payment"].selected is False
    assert statuses["payment"].configured is False
    with pytest.raises(ProviderError):
        payment_adapter()


def test_payment_adapter_selects_stripe_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "payment_provider", "stripe")
    assert isinstance(payment_adapter(), StripeAdapter)


def test_payment_adapter_selects_paypal_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "payment_provider", "paypal")
    assert isinstance(payment_adapter(), PayPalAdapter)


def test_stripe_webhook_signature_accepts_a_valid_signature(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    body = json.dumps({"id": "evt_1", "type": "transfer.reversed"}).encode()
    now = int(time.time())
    header = _stripe_signature(body, "whsec_test", now)
    assert StripeAdapter().verify_webhook(body, header) is True


def test_stripe_webhook_signature_rejects_a_stale_timestamp(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    body = json.dumps({"id": "evt_1", "type": "transfer.reversed"}).encode()
    stale = int(time.time()) - 400
    header = _stripe_signature(body, "whsec_test", stale)
    assert StripeAdapter().verify_webhook(body, header) is False


def test_stripe_webhook_signature_rejects_a_forged_signature(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    body = json.dumps({"id": "evt_1", "type": "transfer.reversed"}).encode()
    now = int(time.time())
    header = _stripe_signature(body, "wrong-secret", now)
    assert StripeAdapter().verify_webhook(body, header) is False


def test_stripe_webhook_signature_rejects_a_missing_header(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    assert StripeAdapter().verify_webhook(b"{}", None) is False


def test_stripe_send_payout_requires_a_configured_secret_key():
    with pytest.raises(ProviderError):
        StripeAdapter()._auth()
