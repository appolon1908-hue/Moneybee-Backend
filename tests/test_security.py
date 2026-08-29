"""
Minimum security test suite for Moneybee-Backend.
Tests auth bypass, webhook signature, and config defaults.
"""

import hashlib
import hmac
import inspect
import os
import time

from app import config
from app.config import Settings


SECURITY_ENV_KEYS = (
    "AUTO_CREATE_SCHEMA",
    "LOCAL_AUTH_BYPASS",
    "LOCAL_IDENTITY_ENFORCEMENT",
    "CODESTRA_MIDDLEWARE_WEBHOOK_TOLERANCE_SECONDS",
    "PROVIDER_WEBHOOK_TOLERANCE_SECONDS",
    "PROVIDER_WEBHOOK_ALLOWLIST_CSV",
    "APP_ENV",
    "MIDDLEWARE_PROVIDER",
)


def isolated_settings(**kwargs) -> Settings:
    original = {key: os.environ.pop(key, None) for key in SECURITY_ENV_KEYS}
    try:
        return Settings(_env_file=None, **kwargs)
    finally:
        for key, value in original.items():
            if value is not None:
                os.environ[key] = value


def default_settings() -> Settings:
    return isolated_settings()


def test_auth_bypass_defaults_to_false():
    """Auth bypass must never be True by default."""
    s = default_settings()
    assert s.local_auth_bypass is False, (
        "local_auth_bypass defaults to True; deployments without an explicit "
        "override would run unauthenticated."
    )


def test_identity_enforcement_defaults_to_true():
    s = default_settings()
    assert s.local_identity_enforcement is True, (
        "local_identity_enforcement defaults to False; identity would not be "
        "enforced in deployments that omit this env var."
    )


def test_auto_create_schema_defaults_to_false():
    s = default_settings()
    assert s.auto_create_schema is False, (
        "auto_create_schema defaults to True; schema must be managed by Alembic."
    )


def test_webhook_tolerance_is_60_seconds_or_less():
    s = default_settings()
    assert s.codestra_middleware_webhook_tolerance_seconds <= 60
    assert s.provider_webhook_tolerance_seconds <= 60


def test_no_twilio_credentials_in_config():
    """Twilio direct access is forbidden. All SMS routes through Middleware."""
    source = inspect.getsource(config)
    assert "twilio_account_sid" not in source.lower()
    assert "twilio_auth_token" not in source.lower()


def test_middleware_provider_warns_when_disabled_in_staging():
    """A non-local, non-test env with middleware disabled must warn loudly."""
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        isolated_settings(app_env="staging", middleware_provider="disabled")
        runtime_warnings = [
            item for item in caught if issubclass(item.category, RuntimeWarning)
        ]
        assert runtime_warnings, (
            "MIDDLEWARE_PROVIDER=disabled in staging must raise a RuntimeWarning."
        )


def _make_signature(body: bytes, secret: str, timestamp: str) -> str:
    signed = timestamp.encode() + b"." + body
    return "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def test_valid_codestra_signature_accepted():
    from app.integration_routes import verify_codestra_signature

    body = b'{"event_type":"test"}'
    secret = "test-secret-123"
    timestamp = str(int(time.time()))
    signature = _make_signature(body, secret, timestamp)
    assert verify_codestra_signature(body, signature, secret, timestamp) is True


def test_invalid_codestra_signature_rejected():
    from app.integration_routes import verify_codestra_signature

    body = b'{"event_type":"test"}'
    secret = "test-secret-123"
    timestamp = str(int(time.time()))
    assert verify_codestra_signature(body, "sha256=invalidsig", secret, timestamp) is False


def test_stale_timestamp_rejected():
    from app.integration_routes import verify_codestra_signature

    body = b'{"event_type":"test"}'
    secret = "test-secret-123"
    old_timestamp = str(int(time.time()) - 300)
    signature = _make_signature(body, secret, old_timestamp)
    assert verify_codestra_signature(
        body, signature, secret, old_timestamp, now=int(time.time())
    ) is False


def test_missing_signature_rejected():
    from app.integration_routes import verify_codestra_signature

    body = b'{"event_type":"test"}'
    assert (
        verify_codestra_signature(body, None, "secret", str(int(time.time()))) is False
    )


def test_missing_secret_rejected():
    from app.integration_routes import verify_codestra_signature

    body = b'{"event_type":"test"}'
    timestamp = str(int(time.time()))
    signature = _make_signature(body, "secret", timestamp)
    assert verify_codestra_signature(body, signature, None, timestamp) is False


def test_missing_timestamp_rejected():
    from app.integration_routes import verify_codestra_signature

    body = b'{"event_type":"test"}'
    secret = "secret"
    signature = _make_signature(body, secret, str(int(time.time())))
    assert verify_codestra_signature(body, signature, secret, None) is False


def test_cors_origins_default_is_localhost_only():
    """Production CORS must be explicitly configured."""
    s = default_settings()
    origins = [origin.strip() for origin in s.cors_origins_csv.split(",")]
    for origin in origins:
        assert "localhost" in origin or "127.0.0.1" in origin, (
            f"Unexpected non-localhost origin in default CORS config: {origin}."
        )
