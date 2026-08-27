from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import identity_models as identity
from app import models
from app.portal.account_schemas import AccountBootstrapRead


BOOTSTRAP_ROUTE = "/auth/bootstrap"
BORROWER_ROLE_CODE = "BORROWER_USER"
EMAIL_ADAPTER = TypeAdapter(EmailStr)


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _allowed_self_registration_clients() -> set[str]:
    raw = os.getenv("ACCOUNT_SELF_REGISTRATION_CLIENT_IDS", "moneybee-borrower")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _registration_source(claims: dict[str, Any]) -> str:
    provider = str(
        claims.get("identity_provider")
        or claims.get("idp")
        or claims.get("kc_idp_hint")
        or ""
    ).strip().lower()
    if provider == "google":
        return "GOOGLE"
    if provider:
        return "BROKERED"
    return "KEYCLOAK_PASSWORD"


def _claim_text(claims: dict[str, Any], name: str, *, required: bool = False) -> str:
    value = str(claims.get(name) or "").strip()
    if required and not value:
        raise _problem(
            "ACCOUNT_CLAIM_MISSING",
            f"The identity token does not include the required {name} claim.",
            422,
        )
    return value


def _identity_values(claims: dict[str, Any]) -> dict[str, str | bool]:
    issuer = _claim_text(claims, "iss", required=True)
    subject = _claim_text(claims, "sub", required=True)
    raw_email = _claim_text(claims, "email", required=True)
    try:
        email = str(EMAIL_ADAPTER.validate_python(raw_email)).lower()
    except ValidationError as exc:
        raise _problem(
            "ACCOUNT_EMAIL_INVALID",
            "The verified Keycloak identity does not include a valid email address.",
            422,
        ) from exc
    if not _truthy(claims.get("email_verified")):
        raise _problem(
            "EMAIL_VERIFICATION_REQUIRED",
            "Verify the email address in Keycloak before creating a MoneyBee account.",
            403,
        )
    username = _claim_text(claims, "preferred_username") or email
    username = username.lower()[:255]
    display_name = (
        _claim_text(claims, "name")
        or " ".join(
            item
            for item in (
                _claim_text(claims, "given_name"),
                _claim_text(claims, "family_name"),
            )
            if item
        ).strip()
        or username
    )[:255]
    client_id = _claim_text(claims, "azp") or _claim_text(claims, "client_id")
    return {
        "issuer": issuer,
        "subject": subject,
        "email": email,
        "username": username,
        "display_name": display_name,
        "client_id": client_id,
        "registration_source": _registration_source(claims),
        "email_verified": True,
    }


def _request_hash(values: dict[str, str | bool]) -> str:
    material = ":".join(
        str(values[key]) for key in ("issuer", "subject", "client_id")
    )
    return hashlib.sha256(material.encode()).hexdigest()


async def _stored_replay(
    db: AsyncSession,
    *,
    subject: str,
    idempotency_key: str,
    request_hash: str,
) -> AccountBootstrapRead | None:
    row = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == subject,
            models.IdempotencyRecord.route == BOOTSTRAP_ROUTE,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise _problem(
            "IDEMPOTENCY_KEY_CONFLICT",
            "The idempotency key was already used for another account identity.",
            409,
        )
    return AccountBootstrapRead.model_validate(row.response_body)


async def _membership_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> tuple[identity.OrganizationMembership, identity.Organization] | None:
    row = (
        await db.execute(
            select(identity.OrganizationMembership, identity.Organization)
            .join(
                identity.Organization,
                identity.Organization.id
                == identity.OrganizationMembership.organization_id,
            )
            .where(
                identity.OrganizationMembership.user_id == user_id,
                identity.OrganizationMembership.active.is_(True),
                identity.Organization.active.is_(True),
            )
            .order_by(identity.OrganizationMembership.created_at)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return row[0], row[1]


async def _email_collision(
    db: AsyncSession,
    email: str,
    *,
    excluding_user_id: uuid.UUID | None = None,
) -> identity.User | None:
    statement = select(identity.User).where(func.lower(identity.User.email) == email)
    if excluding_user_id is not None:
        statement = statement.where(identity.User.id != excluding_user_id)
    return await db.scalar(statement.limit(1))


async def _record_idempotency(
    db: AsyncSession,
    *,
    subject: str,
    idempotency_key: str,
    request_hash: str,
    response: AccountBootstrapRead,
) -> None:
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=subject,
            route=BOOTSTRAP_ROUTE,
            request_hash=request_hash,
            response_status=200,
            response_body=response.model_dump(mode="json"),
        )
    )


async def bootstrap_account(
    db: AsyncSession,
    *,
    claims: dict[str, Any],
    idempotency_key: str,
    request_id: str,
    correlation_id: str,
) -> AccountBootstrapRead:
    values = _identity_values(claims)
    issuer = str(values["issuer"])
    subject = str(values["subject"])
    email = str(values["email"])
    username = str(values["username"])
    display_name = str(values["display_name"])
    request_hash = _request_hash(values)

    replay = await _stored_replay(
        db,
        subject=subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay is not None:
        return replay

    external = await db.scalar(
        select(identity.ExternalIdentity).where(
            identity.ExternalIdentity.issuer == issuer,
            identity.ExternalIdentity.subject == subject,
        )
    )
    now = datetime.now(UTC)
    if external is not None:
        user = await db.get(identity.User, external.user_id)
        membership = await _membership_for_user(db, external.user_id)
        if user is None or not user.active or membership is None:
            raise _problem(
                "ACCOUNT_BINDING_INCOMPLETE",
                "The MoneyBee account binding is incomplete and requires administrator review.",
                409,
            )
        collision = await _email_collision(
            db,
            email,
            excluding_user_id=user.id,
        )
        if collision is not None:
            raise _problem(
                "ACCOUNT_LINK_REVIEW_REQUIRED",
                "The verified email belongs to another MoneyBee account. Automatic linking is blocked.",
                409,
            )
        user.email = email
        user.display_name = display_name
        external.email_at_link_time = email
        external.last_seen_at = now
        membership_row, organization = membership
        response = AccountBootstrapRead(
            created=False,
            user_id=user.id,
            organization_id=organization.id,
            username=username,
            email=email,
            email_verified=True,
            membership_type=membership_row.membership_type,
            registration_source=str(values["registration_source"]),
            welcome_event_status="EXISTING",
            request_id=request_id,
        )
        await _record_idempotency(
            db,
            subject=subject,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response=response,
        )
        await db.commit()
        return response

    client_id = str(values["client_id"])
    if client_id not in _allowed_self_registration_clients():
        raise _problem(
            "INVITATION_REQUIRED",
            "This portal requires an approved MoneyBee invitation. Public self-registration creates borrower accounts only.",
            403,
        )
    if await _email_collision(db, email) is not None:
        raise _problem(
            "ACCOUNT_LINK_REVIEW_REQUIRED",
            "An account with this verified email already exists. Sign in to that account or request administrator-assisted linking.",
            409,
        )

    borrower_role = await db.scalar(
        select(identity.Role).where(
            identity.Role.code == BORROWER_ROLE_CODE,
            identity.Role.active.is_(True),
        )
    )
    if borrower_role is None:
        raise _problem(
            "ACCOUNT_ROLE_NOT_CONFIGURED",
            "The default borrower role has not been provisioned.",
            503,
        )

    user = identity.User(email=email, display_name=display_name, active=True)
    organization = identity.Organization(
        name=f"{display_name} MoneyBee account"[:255],
        organization_type="BORROWER",
        active=True,
    )
    db.add_all([user, organization])
    await db.flush()
    db.add_all(
        [
            identity.ExternalIdentity(
                user_id=user.id,
                issuer=issuer,
                subject=subject,
                email_at_link_time=email,
                last_seen_at=now,
            ),
            identity.OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                membership_type="BORROWER",
                active=True,
            ),
            identity.UserRoleBinding(
                user_id=user.id,
                role_id=borrower_role.id,
                organization_id=organization.id,
                active=True,
            ),
        ]
    )

    response = AccountBootstrapRead(
        created=True,
        user_id=user.id,
        organization_id=organization.id,
        username=username,
        email=email,
        email_verified=True,
        membership_type="BORROWER",
        registration_source=str(values["registration_source"]),
        welcome_event_status="PENDING",
        request_id=request_id,
    )
    db.add(
        models.OutboxEvent(
            event_type="account.registered.v1",
            schema_version=1,
            aggregate_type="user",
            aggregate_id=user.id,
            aggregate_version=1,
            tenant_id=str(organization.id),
            correlation_id=correlation_id,
            causation_id=request_id,
            payload={
                "user_id": str(user.id),
                "organization_id": str(organization.id),
                "membership_type": "BORROWER",
                "username": username,
                "email": email,
                "display_name": display_name,
                "email_verified": True,
                "registration_source": values["registration_source"],
                "identity": {"issuer": issuer, "subject": subject},
                "delivery_intent": {
                    "welcome_email": "KLYROW_VIA_CODESTRA",
                    "crm_projection": "ODOO_VIA_CODESTRA",
                },
            },
            idempotency_key=f"account:{user.id}",
            provider="codestra",
            destination="codestra:account-projection",
        )
    )
    db.add(
        models.AuditEvent(
            actor_id=subject,
            action="ACCOUNT_REGISTERED",
            resource_type="user",
            resource_id=str(user.id),
            request_id=request_id,
            details={
                "organization_id": str(organization.id),
                "membership_type": "BORROWER",
                "registration_source": values["registration_source"],
                "email_verified": True,
                "credentials_stored_by_moneybee": False,
            },
        )
    )
    await _record_idempotency(
        db,
        subject=subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response=response,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await db.scalar(
            select(identity.ExternalIdentity).where(
                identity.ExternalIdentity.issuer == issuer,
                identity.ExternalIdentity.subject == subject,
            )
        )
        if existing is not None:
            return await bootstrap_account(
                db,
                claims=claims,
                idempotency_key=idempotency_key,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        if await _email_collision(db, email) is not None:
            raise _problem(
                "ACCOUNT_LINK_REVIEW_REQUIRED",
                "The verified email was registered by another account while this request was processing.",
                409,
            ) from exc
        raise _problem(
            "ACCOUNT_REGISTRATION_CONFLICT",
            "The account could not be created because another registration completed first.",
            409,
        ) from exc
    return response
