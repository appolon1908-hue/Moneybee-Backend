from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import identity_models as identity
from app import models
from app.auth import Db, decode_access_token
from app.request_context import enforce_portal_client, request_identifiers


router = APIRouter(tags=["account"])
bearer = HTTPBearer(auto_error=False)

BORROWER_ROLE_CODE = "BORROWER_SELF_SERVICE"
ACCOUNT_PROVISIONED_EVENT_TYPE = "codestra.moneybee.account.provisioned"
BORROWER_PERMISSIONS = (
    "application.read.own",
    "application.edit.own",
    "application.submit.own",
    "condition.read.own",
    "complaint.create.own",
    "credit.authorize.own",
    "offer.accept.own",
)


class AccountBootstrapResponse(BaseModel):
    user_id: str
    organization_id: str
    membership_type: str
    email: str
    email_verified: bool
    created: bool


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _claim_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _display_name(claims: dict[str, Any], email: str) -> str:
    explicit = str(claims.get("name") or "").strip()
    if explicit:
        return explicit[:255]
    given = str(claims.get("given_name") or "").strip()
    family = str(claims.get("family_name") or "").strip()
    combined = " ".join(item for item in (given, family) if item).strip()
    return (combined or email.split("@", 1)[0])[:255]


def _require_active_borrower_membership(membership: identity.OrganizationMembership) -> None:
    if not membership.active:
        raise _problem(
            "MEMBERSHIP_INACTIVE",
            "The MoneyBee borrower membership is disabled.",
            403,
        )


async def verified_borrower_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict[str, Any]:
    if credentials is None:
        raise _problem("AUTHENTICATION_REQUIRED", "Authentication is required.", 401)

    claims = decode_access_token(credentials.credentials)
    enforce_portal_client(request.url.path, claims)

    if not _claim_bool(claims.get("email_verified")):
        raise _problem(
            "EMAIL_VERIFICATION_REQUIRED",
            "Verify your email address in Keycloak before creating a MoneyBee account.",
            403,
        )

    email = str(claims.get("email") or "").strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise _problem(
            "VERIFIED_EMAIL_REQUIRED",
            "A verified email claim is required to create a MoneyBee account.",
            403,
        )
    claims["email"] = email
    return claims


async def _ensure_role_and_permissions(
    db: AsyncSession,
    *,
    user_id,
    organization_id,
) -> None:
    role = await db.scalar(select(identity.Role).where(identity.Role.code == BORROWER_ROLE_CODE))
    if role is None:
        role = identity.Role(
            code=BORROWER_ROLE_CODE,
            description="Default least-privilege role for self-registered MoneyBee borrowers.",
            active=True,
        )
        db.add(role)
        await db.flush()
    elif not role.active:
        role.active = True

    for permission_code in BORROWER_PERMISSIONS:
        permission = await db.scalar(
            select(identity.Permission).where(identity.Permission.code == permission_code)
        )
        if permission is None:
            permission = identity.Permission(
                code=permission_code,
                description="Borrower self-service permission provisioned by account bootstrap.",
            )
            db.add(permission)
            await db.flush()
        link = await db.scalar(
            select(identity.RolePermission).where(
                identity.RolePermission.role_id == role.id,
                identity.RolePermission.permission_id == permission.id,
            )
        )
        if link is None:
            db.add(identity.RolePermission(role_id=role.id, permission_id=permission.id))

    binding = await db.scalar(
        select(identity.UserRoleBinding).where(
            identity.UserRoleBinding.user_id == user_id,
            identity.UserRoleBinding.role_id == role.id,
            identity.UserRoleBinding.organization_id == organization_id,
        )
    )
    if binding is None:
        db.add(
            identity.UserRoleBinding(
                user_id=user_id,
                role_id=role.id,
                organization_id=organization_id,
                active=True,
            )
        )
    elif not binding.active:
        binding.active = True


async def _provision(
    db: AsyncSession,
    request: Request,
    claims: dict[str, Any],
) -> AccountBootstrapResponse:
    issuer = str(claims["iss"])
    subject = str(claims["sub"])
    email = str(claims["email"])
    display_name = _display_name(claims, email)
    identifiers = request_identifiers(request)

    external = await db.scalar(
        select(identity.ExternalIdentity).where(
            identity.ExternalIdentity.issuer == issuer,
            identity.ExternalIdentity.subject == subject,
        )
    )
    created = external is None

    if external is None:
        user = identity.User(email=email, display_name=display_name, active=True)
        organization = identity.Organization(
            name=f"{display_name}'s business"[:255],
            organization_type="BORROWER",
            active=True,
        )
        db.add_all([user, organization])
        await db.flush()
        external = identity.ExternalIdentity(
            user_id=user.id,
            issuer=issuer,
            subject=subject,
            email_at_link_time=email,
        )
        membership = identity.OrganizationMembership(
            organization_id=organization.id,
            user_id=user.id,
            membership_type="BORROWER",
            active=True,
        )
        db.add_all([external, membership])
    else:
        user = await db.get(identity.User, external.user_id)
        if user is None:
            raise _problem(
                "IDENTITY_NOT_BOUND",
                "The Keycloak identity is linked to a missing MoneyBee user.",
                409,
            )
        if not user.active:
            raise _problem("USER_DISABLED", "The MoneyBee account is disabled.", 403)
        if not user.email:
            user.email = email
        if not user.display_name:
            user.display_name = display_name
        membership = await db.scalar(
            select(identity.OrganizationMembership).where(
                identity.OrganizationMembership.user_id == user.id,
                identity.OrganizationMembership.membership_type == "BORROWER",
            )
        )
        if membership is None:
            organization = identity.Organization(
                name=f"{display_name}'s business"[:255],
                organization_type="BORROWER",
                active=True,
            )
            db.add(organization)
            await db.flush()
            membership = identity.OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                membership_type="BORROWER",
                active=True,
            )
            db.add(membership)
        else:
            _require_active_borrower_membership(membership)
            organization = await db.get(identity.Organization, membership.organization_id)
            if organization is None:
                raise _problem(
                    "TENANT_CONFIGURATION_INVALID",
                    "The borrower membership references a missing organization.",
                    409,
                )
            if not organization.active:
                raise _problem(
                    "TENANT_ACCESS_DENIED",
                    "The borrower organization is disabled.",
                    403,
                )

    await _ensure_role_and_permissions(
        db,
        user_id=user.id,
        organization_id=organization.id,
    )

    event_key = hashlib.sha256(
        f"{ACCOUNT_PROVISIONED_EVENT_TYPE}|{issuer}|{subject}".encode("utf-8")
    ).hexdigest()
    prior_event = await db.scalar(
        select(models.OutboxEvent).where(models.OutboxEvent.idempotency_key == event_key)
    )
    if prior_event is None:
        db.add(
            models.OutboxEvent(
                event_type=ACCOUNT_PROVISIONED_EVENT_TYPE,
                schema_version=1,
                aggregate_type="user",
                aggregate_id=user.id,
                aggregate_version=1,
                tenant_id=str(organization.id),
                correlation_id=identifiers.correlation_id,
                causation_id=identifiers.request_id,
                payload={
                    "user_id": str(user.id),
                    "organization_id": str(organization.id),
                    "membership_type": "BORROWER",
                    "email": email,
                    "email_verified": True,
                },
                idempotency_key=event_key,
            )
        )
        db.add(
            models.AuditEvent(
                actor_id=f"oidc:{subject}"[:200],
                action="account.bootstrap",
                resource_type="user",
                resource_id=str(user.id),
                request_id=identifiers.request_id,
                details={
                    "organization_id": str(organization.id),
                    "membership_type": "BORROWER",
                    "created": created,
                },
            )
        )

    await db.commit()
    return AccountBootstrapResponse(
        user_id=str(user.id),
        organization_id=str(organization.id),
        membership_type="BORROWER",
        email=email,
        email_verified=True,
        created=created,
    )


@router.post("/account/bootstrap", response_model=AccountBootstrapResponse)
async def bootstrap_account(
    request: Request,
    db: Db,
    claims: Annotated[dict[str, Any], Depends(verified_borrower_claims)],
) -> AccountBootstrapResponse:
    try:
        return await _provision(db, request, claims)
    except IntegrityError:
        # A concurrent first-login bootstrap may win the unique issuer+subject or
        # outbox idempotency race. Roll back and resolve the now-existing account.
        await db.rollback()
        return await _provision(db, request, claims)
