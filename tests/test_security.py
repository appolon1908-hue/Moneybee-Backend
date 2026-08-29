"""
Security test suite for Moneybee-Backend.

Covers config defaults, auth bypass warnings, webhook signatures, rate limiting,
portal path enforcement, integration adapter safety, and CORS defaults.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import warnings
from unittest.mock import MagicMock

import pytest

from app.config import Settings


SECURITY_ENV_KEYS = (
    "APP_ENV",
    "AUTO_CREATE_SCHEMA",
    "LOCAL_AUTH_BYPASS",
    "LOCAL_IDENTITY_ENFORCEMENT",
    "CODESTRA_MIDDLEWARE_WEBHOOK_TOLERANCE_SECONDS",
    "PROVIDER_WEBHOOK_TOLERANCE_SECONDS",
    "PROVIDER_WEBHOOK_ALLOWLIST_CSV",
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


class TestConfigDefaults:
    """Settings with no env vars must fail safely."""

    def test_auth_bypass_defaults_to_false(self):
        settings = isolated_settings()
        assert settings.local_auth_bypass is False

    def test_identity_enforcement_defaults_to_true(self):
        settings = isolated_settings()
        assert settings.local_identity_enforcement is True

    def test_auto_create_schema_defaults_to_false(self):
        settings = isolated_settings()
        assert settings.auto_create_schema is False

    def test_webhook_tolerance_is_60_seconds_or_less(self):
        settings = isolated_settings()
        assert settings.codestra_middleware_webhook_tolerance_seconds <= 60
        assert settings.provider_webhook_tolerance_seconds <= 60

    def test_twilio_not_in_default_allowlist(self):
        settings = isolated_settings()
        allowlist = [
            provider.strip()
            for provider in settings.provider_webhook_allowlist_csv.split(",")
        ]
        assert "twilio" not in allowlist

    def test_middleware_provider_warns_in_staging(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            isolated_settings(app_env="staging", middleware_provider="disabled")
            runtime_warnings = [
                item for item in caught if issubclass(item.category, RuntimeWarning)
            ]
            assert runtime_warnings
            assert "MIDDLEWARE_PROVIDER=disabled" in str(runtime_warnings[0].message)

    def test_auth_bypass_warns_and_fails_in_staging(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(ValueError):
                isolated_settings(app_env="staging", local_auth_bypass=True)
            runtime_warnings = [
                item for item in caught if issubclass(item.category, RuntimeWarning)
            ]
            assert any(
                "LOCAL_AUTH_BYPASS=true" in str(item.message)
                for item in runtime_warnings
            )

    def test_local_settings_do_not_warn(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            isolated_settings(
                app_env="local",
                local_auth_bypass=True,
                middleware_provider="disabled",
            )
            runtime_warnings = [
                item for item in caught if issubclass(item.category, RuntimeWarning)
            ]
            assert not runtime_warnings


class TestWebhookSignatureVerification:
    """Inbound webhook signatures must fail closed."""

    @staticmethod
    def _make_sig(body: bytes, secret: str, timestamp: str) -> str:
        signed = timestamp.encode() + b"." + body
        digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature_accepted(self):
        from app.integration_routes import verify_codestra_signature

        body = b'{"event_type":"lead.created.v1"}'
        secret = "test-webhook-secret"
        timestamp = str(int(time.time()))
        signature = self._make_sig(body, secret, timestamp)
        assert verify_codestra_signature(body, signature, secret, timestamp) is True

    def test_wrong_secret_rejected(self):
        from app.integration_routes import verify_codestra_signature

        body = b'{"event_type":"lead.created.v1"}'
        timestamp = str(int(time.time()))
        signature = self._make_sig(body, "correct-secret", timestamp)
        assert verify_codestra_signature(body, signature, "wrong-secret", timestamp) is False

    def test_tampered_body_rejected(self):
        from app.integration_routes import verify_codestra_signature

        body = b'{"event_type":"lead.created.v1"}'
        secret = "test-secret"
        timestamp = str(int(time.time()))
        signature = self._make_sig(body, secret, timestamp)
        tampered = b'{"event_type":"admin.override.v1"}'
        assert verify_codestra_signature(tampered, signature, secret, timestamp) is False

    def test_stale_timestamp_rejected(self):
        from app.integration_routes import verify_codestra_signature

        now = int(time.time())
        body = b'{"event_type":"test"}'
        secret = "test-secret"
        old_timestamp = str(now - 61)
        signature = self._make_sig(body, secret, old_timestamp)
        assert verify_codestra_signature(
            body, signature, secret, old_timestamp, now=now
        ) is False

    def test_future_timestamp_rejected(self):
        from app.integration_routes import verify_codestra_signature

        now = int(time.time())
        body = b'{"event_type":"test"}'
        secret = "test-secret"
        future = str(now + 3600)
        signature = self._make_sig(body, secret, future)
        assert verify_codestra_signature(body, signature, secret, future, now=now) is False

    def test_missing_signature_rejected(self):
        from app.integration_routes import verify_codestra_signature

        body = b'{"event_type":"test"}'
        timestamp = str(int(time.time()))
        assert verify_codestra_signature(body, None, "secret", timestamp) is False

    def test_missing_secret_rejected(self):
        from app.integration_routes import verify_codestra_signature

        body = b'{"event_type":"test"}'
        timestamp = str(int(time.time()))
        signature = self._make_sig(body, "secret", timestamp)
        assert verify_codestra_signature(body, signature, None, timestamp) is False

    def test_missing_timestamp_rejected(self):
        from app.integration_routes import verify_codestra_signature

        body = b'{"event_type":"test"}'
        secret = "secret"
        signature = self._make_sig(body, secret, str(int(time.time())))
        assert verify_codestra_signature(body, signature, secret, None) is False

    def test_non_numeric_timestamp_rejected(self):
        from app.integration_routes import verify_codestra_signature

        body = b'{"event_type":"test"}'
        assert verify_codestra_signature(
            body, "sha256=abc", "secret", "notanumber"
        ) is False

    def test_replay_within_window_accepted(self):
        from app.integration_routes import verify_codestra_signature

        now = int(time.time())
        body = b'{"event_type":"test"}'
        secret = "test-secret"
        timestamp = str(now - 30)
        signature = self._make_sig(body, secret, timestamp)
        assert verify_codestra_signature(body, signature, secret, timestamp, now=now) is True


class TestRateLimit:
    """Rate limiting protects public and webhook endpoints from abuse."""

    def setup_method(self):
        from app.rate_limit import reset_rate_limit_state

        reset_rate_limit_state()

    def _make_request(self, path: str, client_ip: str = "1.2.3.4"):
        request = MagicMock()
        request.url.path = path
        request.headers.get = (
            lambda key, default="": "" if key == "X-Forwarded-For" else default
        )
        request.client.host = client_ip
        return request

    def test_public_endpoint_rate_limited_after_threshold(self):
        import app.rate_limit as rate_limit
        from app.rate_limit import check_request_rate_limit

        original = rate_limit.settings
        rate_limit.settings = isolated_settings(public_rate_limit_per_minute=3)
        try:
            request = self._make_request("/api/v2/public/prequalifications")
            results = [check_request_rate_limit(request) for _ in range(4)]
            assert results[2] is not None and not results[2].limited
            assert results[3] is not None and results[3].limited
        finally:
            rate_limit.settings = original

    def test_non_rate_limited_path_returns_none(self):
        from app.rate_limit import check_request_rate_limit

        request = self._make_request("/api/v2/borrower/applications")
        assert check_request_rate_limit(request) is None

    def test_rate_limit_disabled_returns_none(self):
        import app.rate_limit as rate_limit
        from app.rate_limit import check_request_rate_limit

        original = rate_limit.settings
        rate_limit.settings = isolated_settings(rate_limit_enabled=False)
        try:
            request = self._make_request("/api/v2/public/contact-requests")
            assert check_request_rate_limit(request) is None
        finally:
            rate_limit.settings = original

    def test_different_clients_have_separate_buckets(self):
        import app.rate_limit as rate_limit
        from app.rate_limit import check_request_rate_limit

        original = rate_limit.settings
        rate_limit.settings = isolated_settings(public_rate_limit_per_minute=2)
        try:
            request_a = self._make_request("/api/v2/public/callback-requests", "10.0.0.1")
            request_b = self._make_request("/api/v2/public/callback-requests", "10.0.0.2")
            check_request_rate_limit(request_a)
            check_request_rate_limit(request_a)
            third_a = check_request_rate_limit(request_a)
            first_b = check_request_rate_limit(request_b)
            assert third_a is not None and third_a.limited is True
            assert first_b is not None and first_b.limited is False
        finally:
            rate_limit.settings = original


class TestPortalClientEnforcement:
    """Each portal prefix must map to the correct OIDC client family."""

    def test_borrower_client_allowed_on_borrower_path(self):
        from app.request_context import _portals_for_path

        portals = _portals_for_path("/api/v2/borrower/applications")
        assert portals is not None and "borrower" in portals

    def test_lender_path_not_accessible_to_borrower(self):
        from app.request_context import _portals_for_path

        portals = _portals_for_path("/api/v2/lender/workspace")
        assert portals is not None
        assert "borrower" not in portals
        assert "lender" in portals

    def test_admin_path_not_accessible_to_borrower_or_lender(self):
        from app.request_context import _portals_for_path

        portals = _portals_for_path("/api/v2/admin/organizations")
        assert portals is not None
        assert "borrower" not in portals
        assert "lender" not in portals
        assert "admin" in portals

    def test_public_path_has_no_portal_restriction(self):
        from app.request_context import _portals_for_path

        portals = _portals_for_path("/api/v2/public/prequalifications")
        assert portals is None


class TestIntegrationAdapterSafety:
    """Adapters must raise ProviderError, not crash, when misconfigured."""

    def test_middleware_adapter_raises_when_disabled(self):
        import app.integrations.registry as registry
        from app.integrations.base import ProviderError
        from app.integrations.registry import middleware_adapter

        original = registry.settings
        registry.settings = isolated_settings(middleware_provider="disabled")
        try:
            with pytest.raises(ProviderError) as exc_info:
                middleware_adapter()
            assert "disabled" in str(exc_info.value).lower()
        finally:
            registry.settings = original

    def test_bank_adapter_raises_when_no_provider_set(self):
        import app.integrations.registry as registry
        from app.integrations.base import ProviderError
        from app.integrations.registry import bank_adapter

        original = registry.settings
        registry.settings = isolated_settings()
        try:
            with pytest.raises(ProviderError) as exc_info:
                bank_adapter()
            assert "disabled" in str(exc_info.value).lower()
        finally:
            registry.settings = original


class TestCORSDefaults:
    """CORS defaults must be localhost-only."""

    def test_cors_origins_default_to_localhost(self):
        settings = isolated_settings()
        origins = [origin.strip() for origin in settings.cors_origins_csv.split(",")]
        for origin in origins:
            assert "localhost" in origin or "127.0.0.1" in origin, (
                f"Non-localhost origin in default CORS config: {origin}."
            )
