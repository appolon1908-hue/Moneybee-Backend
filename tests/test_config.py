import pytest

from app.config import Settings


def test_rejects_deprecated_identity_host() -> None:
    with pytest.raises(ValueError):
        Settings(keycloak_issuer="https://auth.codestra." + "agency/realms/codestra", auth_required=True)


def test_production_requires_auth() -> None:
    with pytest.raises(ValueError):
        Settings(environment="production", auth_required=False, webhook_shared_secret="valid-secret")
