import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

import pytest

from app.encryption import decrypt_secret, encrypt_secret, rewrap_secret
from app.integrations.base import ProviderError


def test_encrypt_round_trips_and_prefixes_the_active_key_version():
    token = encrypt_secret("plaid-access-token-abc123")
    assert token.startswith("1:")
    assert decrypt_secret(token) == "plaid-access-token-abc123"


def test_decrypt_rejects_a_value_with_no_version_prefix():
    with pytest.raises(ProviderError):
        decrypt_secret("not-a-versioned-ciphertext")


def test_decrypt_rejects_an_unknown_key_version():
    with pytest.raises(ProviderError):
        decrypt_secret("99:some-token")


def test_rewrap_produces_a_value_that_still_decrypts_to_the_same_plaintext():
    original = encrypt_secret("broker-tin-123-45-6789")
    rewrapped = rewrap_secret(original)
    assert decrypt_secret(rewrapped) == "broker-tin-123-45-6789"
