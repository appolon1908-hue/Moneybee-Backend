import hashlib
import hmac

import pytest
from fastapi import HTTPException

from app.webhook_gateway_routes import (
    _signature_digest,
    _timestamp,
    _verify_signature,
)


def test_signature_binds_timestamp_event_id_and_body(monkeypatch) -> None:
    monkeypatch.setenv("MONEYBEE_WEBHOOK_SECRET_TEST_PROVIDER", "current-secret")
    body = b'{"status":"approved"}'
    timestamp = 1_700_000_000
    event_id = "evt_123"
    signature = _signature_digest(
        secret="current-secret",
        timestamp=timestamp,
        event_id=event_id,
        body=body,
    )
    _verify_signature(
        provider="test-provider",
        timestamp=timestamp,
        event_id=event_id,
        body=body,
        supplied_signature=f"v1={signature}",
    )
    tampered = hmac.new(
        b"current-secret",
        str(timestamp).encode() + b"." + event_id.encode() + b"." + body + b"x",
        hashlib.sha256,
    ).hexdigest()
    with pytest.raises(HTTPException) as exc_info:
        _verify_signature(
            provider="test-provider",
            timestamp=timestamp,
            event_id=event_id,
            body=body,
            supplied_signature=tampered,
        )
    assert exc_info.value.status_code == 401


def test_secret_rotation_accepts_previous_secret(monkeypatch) -> None:
    monkeypatch.delenv("MONEYBEE_WEBHOOK_SECRET_ROTATING", raising=False)
    monkeypatch.setenv(
        "MONEYBEE_WEBHOOK_SECRETS_JSON",
        '{"rotating":["current-secret","previous-secret"]}',
    )
    body = b"{}"
    timestamp = 1_700_000_000
    event_id = "evt_rotated"
    signature = _signature_digest(
        secret="previous-secret",
        timestamp=timestamp,
        event_id=event_id,
        body=body,
    )
    _verify_signature(
        provider="rotating",
        timestamp=timestamp,
        event_id=event_id,
        body=body,
        supplied_signature=signature,
    )


def test_replay_window_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("MONEYBEE_WEBHOOK_TOLERANCE_SECONDS", "300")
    assert _timestamp("1000", now=1200) == 1000
    with pytest.raises(HTTPException) as exc_info:
        _timestamp("1000", now=1301)
    assert exc_info.value.status_code == 401
