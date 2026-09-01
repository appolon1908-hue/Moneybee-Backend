from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
import uuid

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.identity import IdentityResolutionError, resolve_identity
from app.request_context import enforce_portal_client


bearer = HTTPBearer(auto_error=False)
Db = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    issuer: str
    subject: str
    organization_ids: tuple[uuid.UUID, ...]
    active_organization_id: uuid.UUID | None
    roles: frozenset[str]
    permissions: frozenset[str]
    membership_types: frozenset[str]
    borrower_id: uuid.UUID | None
    lender_id: uuid.UUID | None
    is_active: bool

    @property
    def organization_id(self) -> str | None:
        """Compatibility accessor for code migrating to active_organization_id."""
        if self.active_organization_id is None:
            return None
        return str(self.active_organization_id)


LEGACY_ROLE_PERMISSIONS = {
    "MONEYBEE_ADMIN": {"*"},
    "MONEYBEE_SALES": {"lead.read", "application.read", "application.edit"},
    "MONEYBEE_UNDERWRITER": {
        "application.read",
        "underwriting.review",
        "matching.run",
        "fraud.run",
        "kyb.run",
    },
    "LENDER_ADMIN": {
        "lender.application.read",
        "lender.submission.read",
        "lender.condition.create",
        "lender.condition.review",
        "offer.create",
        "program.manage",
    },
    "LENDER_UNDERWRITER": {
        "lender.application.read",
        "lender.submission.read",
        "lender.condition.create",
        "offer.create",
    },
    "BORROWER": {
        "application.read.own",
        "application.edit.own",
        "application.submit.own",
        "condition.read.own",
        "complaint.create.own",
        "credit.authorize.own",
        "offer.accept.own",
        "offer.decline.own",
    },
}


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
        headers=headers,
    )


def _legacy_permissions(roles: set[str]) -> frozenset[str]:
    values: set[str] = set()
    for role in roles:
        values.update(LEGACY_ROLE_PERMISSIONS.get(role, set()))
    return frozenset(values)


@lru_cache
def jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(settings.oidc_jwks_url)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
        if not header.get("kid"):
            raise jwt.InvalidTokenError("kid is required")
        if header.get("alg") not in settings.oidc_algorithms:
            raise jwt.InvalidAlgorithmError("algorithm is not allowed")
        signing_key = jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=settings.oidc_algorithms,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nbf"]},
        )
    except jwt.PyJWTError as exc:
        raise _problem(
            "INVALID_ACCESS_TOKEN",
            "The access token is invalid or expired.",
            401,
        ) from exc
    except Exception as exc:
        raise _problem(
            "IDENTITY_PROVIDER_UNAVAILABLE",
            "The identity provider could not be reached.",
            503,
        ) from exc


def _requested_organization_id(
    request: Request,
    claims: dict[str, Any] | None = None,
) -> str | None:
    return (
        request.headers.get("X-Organization-ID")
        or (claims or {}).get("organization_id")
        or (claims or {}).get("org_id")
    )


def _local_bypass_principal(request: Request) -> Principal:
    requested = _requested_organization_id(request)
    selected: uuid.UUID | None = None
    if requested:
        try:
            selected = uuid.UUID(str(requested))
        except ValueError as exc:
            raise _problem(
                "INVALID_ORGANIZATION_CONTEXT",
                "X-Organization-ID must be a UUID.",
                422,
            ) from exc
    organizations = (selected,) if selected else ()
    return Principal(
        user_id=uuid.UUID(int=0),
        issuer="local-bypass",
        subject="local-admin",
        organization_ids=organizations,
        active_organization_id=selected,
        roles=frozenset({"MONEYBEE_ADMIN"}),
        permissions=frozenset({"*"}),
        membership_types=frozenset({"MONEYBEE"}),
        borrower_id=selected,
        lender_id=selected,
        is_active=True,
    )


def _legacy_claims_principal(claims: dict[str, Any]) -> Principal:
    roles = set(claims.get("realm_access", {}).get("roles", []))
    raw_organization_id = claims.get("organization_id") or claims.get("org_id")
    try:
        organization_id = uuid.UUID(str(raw_organization_id)) if raw_organization_id else None
    except ValueError:
        organization_id = None
    membership_types = {
        membership
        for membership in ("BORROWER", "LENDER", "MONEYBEE")
        if membership in roles
        or (
            membership == "MONEYBEE"
            and any(role.startswith("MONEYBEE_") for role in roles)
        )
    }
    subject = str(claims["sub"])
    return Principal(
        user_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{claims['iss']}:{subject}"),
        issuer=str(claims["iss"]),
        subject=subject,
        organization_ids=(organization_id,) if organization_id else (),
        active_organization_id=organization_id,
        roles=frozenset(roles),
        permissions=_legacy_permissions(roles),
        membership_types=frozenset(membership_types),
        borrower_id=organization_id if "BORROWER" in membership_types else None,
        lender_id=organization_id if "LENDER" in membership_types else None,
        is_active=True,
    )


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Db,
) -> Principal:
    if settings.local_auth_bypass and settings.app_env in {"local", "test"}:
        return _local_bypass_principal(request)
    if credentials is None:
        raise _problem("AUTHENTICATION_REQUIRED", "Authentication is required.", 401)

    claims = decode_access_token(credentials.credentials)
    enforce_portal_client(request.url.path, claims)
    requested_organization_id = _requested_organization_id(request, claims)
    try:
        resolved = await resolve_identity(
            db,
            issuer=str(claims["iss"]),
            subject=str(claims["sub"]),
            requested_organization_id=requested_organization_id,
        )
    except IdentityResolutionError as exc:
        if (
            not settings.local_identity_enforcement
            and settings.app_env in {"local", "test", "dev"}
            and exc.code == "IDENTITY_NOT_BOUND"
        ):
            return _legacy_claims_principal(claims)
        raise _problem(exc.code, str(exc), exc.status_code) from exc

    return Principal(
        user_id=resolved.user_id,
        issuer=resolved.issuer,
        subject=resolved.subject,
        organization_ids=resolved.organization_ids,
        active_organization_id=resolved.active_organization_id,
        roles=resolved.roles,
        permissions=resolved.permissions,
        membership_types=resolved.membership_types,
        borrower_id=resolved.borrower_id,
        lender_id=resolved.lender_id,
        is_active=resolved.is_active,
    )


def require_permission(permission: str):
    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if "*" not in principal.permissions and permission not in principal.permissions:
            raise _problem(
                "PERMISSION_DENIED",
                "The principal does not have the required permission.",
                403,
            )
        return principal

    return dependency
