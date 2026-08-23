from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
import jwt
import pytest

from app import auth
from app.config import settings


PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwksClient:
    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        return SimpleNamespace(key=PRIVATE_KEY.public_key())


def token(**overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": settings.oidc_issuer,
        "sub": "keycloak-subject",
        "aud": settings.oidc_audience,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nbf": now - timedelta(seconds=1),
    }
    claims.update(overrides)
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch):
    monkeypatch.setattr(auth, "jwks_client", lambda: FakeJwksClient())


def assert_invalid_access_token(value: str) -> None:
    with pytest.raises(HTTPException) as caught:
        auth.decode_access_token(value)
    assert caught.value.status_code == 401
    assert caught.value.detail["code"] == "INVALID_ACCESS_TOKEN"


def test_valid_token_requires_and_validates_all_oidc_claims():
    claims = auth.decode_access_token(token())
    assert claims["iss"] == settings.oidc_issuer
    assert claims["sub"] == "keycloak-subject"


@pytest.mark.parametrize("claim", ["sub", "exp", "iat", "nbf", "aud", "iss"])
def test_required_claim_is_rejected_when_missing(claim: str):
    now = datetime.now(UTC)
    claims = {
        "iss": settings.oidc_issuer,
        "sub": "keycloak-subject",
        "aud": settings.oidc_audience,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nbf": now - timedelta(seconds=1),
    }
    claims.pop(claim)
    value = jwt.encode(
        claims,
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    assert_invalid_access_token(value)


def test_wrong_issuer_is_rejected():
    assert_invalid_access_token(token(iss="https://issuer.invalid/realms/wrong"))


def test_wrong_audience_is_rejected():
    assert_invalid_access_token(token(aud="another-api"))


def test_expired_token_is_rejected():
    assert_invalid_access_token(token(exp=datetime.now(UTC) - timedelta(seconds=1)))
