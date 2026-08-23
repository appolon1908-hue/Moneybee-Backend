from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[str]
    permissions: frozenset[str]
    organization_id: str | None = None


ROLE_PERMISSIONS = {
    "MONEYBEE_ADMIN": {"*"},
    "MONEYBEE_SALES": {"lead.read", "application.read", "application.edit"},
    "MONEYBEE_UNDERWRITER": {"application.read", "underwriting.review", "matching.run"},
    "LENDER_ADMIN": {"lender.application.read", "offer.create", "program.manage"},
    "LENDER_UNDERWRITER": {"lender.application.read", "offer.create"},
    "BORROWER": {
        "application.read.own",
        "application.edit.own",
        "application.submit.own",
        "offer.accept.own",
    },
}


def permission_set(roles: set[str]) -> frozenset[str]:
    values: set[str] = set()
    for role in roles:
        values.update(ROLE_PERMISSIONS.get(role, set()))
    return frozenset(values)


async def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if settings.local_auth_bypass and settings.app_env in {"local", "test"}:
        return Principal("local-admin", frozenset({"MONEYBEE_ADMIN"}), frozenset({"*"}))
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        signing_key = jwt.PyJWKClient(settings.oidc_jwks_url).get_signing_key_from_jwt(
            credentials.credentials
        )
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc
    roles = set(claims.get("realm_access", {}).get("roles", []))
    organization_id = claims.get("organization_id") or claims.get("org_id")
    return Principal(
        str(claims["sub"]),
        frozenset(roles),
        permission_set(roles),
        str(organization_id) if organization_id else None,
    )


def require_permission(permission: str):
    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if "*" not in principal.permissions and permission not in principal.permissions:
            raise HTTPException(status_code=403, detail="Permission denied")
        return principal

    return dependency
