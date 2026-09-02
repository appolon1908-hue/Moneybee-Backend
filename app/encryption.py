from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.integrations.base import ProviderError

_ENVELOPE_PREFIX = "mbenc"


def _fernet_for_version(version: str) -> Fernet:
    keys = settings.field_encryption_keys
    key = keys.get(version)
    if not key:
        raise ProviderError(
            "encryption",
            f"No field encryption key configured for version {version!r}",
        )
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            "encryption",
            f"Field encryption key for version {version!r} is invalid",
        ) from exc


def encrypt_secret(value: str) -> str:
    version = settings.current_field_encryption_version
    if not version:
        raise ProviderError(
            "encryption",
            "FIELD_ENCRYPTION_CURRENT_VERSION is not configured",
        )
    token = _fernet_for_version(version).encrypt(value.encode()).decode()
    return f"{_ENVELOPE_PREFIX}:{version}:{token}"


def decrypt_secret(value: str) -> str:
    parts = value.split(":", 2)
    if len(parts) == 3 and parts[0] == _ENVELOPE_PREFIX:
        _, version, token = parts
    elif len(parts) == 2:
        # Backward-compatible reader for the previously emitted ``version:token``.
        version, token = parts
    else:
        raise ProviderError(
            "encryption",
            "Encrypted value is missing its key-version prefix",
        )
    try:
        return _fernet_for_version(version).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ProviderError(
            "encryption",
            "Encrypted provider credential cannot be decrypted",
        ) from exc


def rewrap_secret(value: str) -> str:
    """Decrypts with whichever key version the ciphertext names, then
    re-encrypts under the current active version. Used to migrate a stored
    value onto a newly-rotated key without a flag-day re-encryption of
    every row at once - callers can rewrap opportunistically (e.g. on next
    read) or via a dedicated rotation script that walks affected tables."""
    return encrypt_secret(decrypt_secret(value))
