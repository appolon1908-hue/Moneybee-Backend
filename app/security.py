import asyncio
import time
from dataclasses import dataclass
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

settings = get_settings()
bearer = HTTPBearer(auto_error=False)
_jwks: dict[str, object] | None = None
_jwks_expires_at = 0.0
_jwks_lock = asyncio.Lock()


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[str]


async def _get_jwks() -> dict[str, object]:
    global _jwks, _jwks_expires_at
    now = time.monotonic()
    if _jwks is not None and now < _jwks_expires_at:
        return _jwks
    async with _jwks_lock:
        now = time.monotonic()
        if _jwks is not None and now < _jwks_expires_at:
            return _jwks
        url = f"{settings.keycloak_issuer}/protocol/openid-connect/certs"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        _jwks = payload
        _jwks_expires_at = now + 300
        return payload


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None:
        if not settings.auth_required:
            return Principal("development-user", frozenset({"borrower", "admin"}))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    try:
        header = jwt.get_unverified_header(credentials.credentials)
        kid = header.get("kid")
        jwks = await _get_jwks()
        key_data = next(key for key in jwks.get("keys", []) if key.get("kid") == kid)  # type: ignore[union-attr]
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
        claims = jwt.decode(
            credentials.credentials,
            public_key,
            algorithms=["RS256"],
            audience=settings.keycloak_audience,
            issuer=settings.keycloak_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except (StopIteration, httpx.HTTPError, jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc

    roles = frozenset(claims.get("realm_access", {}).get("roles", []))
    return Principal(subject=str(claims["sub"]), roles=roles)


def require_roles(*required: str):
    async def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not principal.roles.intersection(required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return principal

    return dependency
