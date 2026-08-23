from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.integrations.base import ProviderError


def _fernet() -> Fernet:
    if not settings.field_encryption_key:
        raise ProviderError(
            "encryption",
            "FIELD_ENCRYPTION_KEY is not configured",
        )
    try:
        return Fernet(settings.field_encryption_key.encode())
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            "encryption",
            "FIELD_ENCRYPTION_KEY is invalid",
        ) from exc


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ProviderError(
            "encryption",
            "Encrypted provider credential cannot be decrypted",
        ) from exc
