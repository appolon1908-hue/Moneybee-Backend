import json
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import identity_models as identity
from app import models
from app.db import SessionLocal
from app.identity import resolve_identity
from app.portal.account_service import bootstrap_account


DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql+asyncpg://"),
    reason="PostgreSQL account-registration persistence test",
)


def claims(*, subject: str, email: str, verified: bool = True, client_id: str = "moneybee-borrower"):
    return {
        "iss": "https://auth.codestra.co/realms/codestra",
        "sub": subject,
        "aud": "moneybee-api",
        "azp": client_id,
        "preferred_username": email.split("@", 1)[0],
        "email": email,
        "email_verified": verified,
        "name": "Verified Borrower",
    }


@pytest.mark.asyncio
async def test_verified_keycloak_account_bootstrap_is_idempotent(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SELF_REGISTRATION_CLIENT_IDS", "moneybee-borrower")
    suffix = uuid.uuid4().hex
    subject = f"account-{suffix}"
    email = f"account-{suffix}@example.com"
    key = f"bootstrap-{suffix}"

    async with SessionLocal() as db:
        created = await bootstrap_account(
            db,
            claims=claims(subject=subject, email=email),
            idempotency_key=key,
            request_id=f"request-{suffix}",
            correlation_id=f"correlation-{suffix}",
        )
        assert created.created is True
        assert created.membership_type == "BORROWER"
        assert created.email_verified is True

    async with SessionLocal() as db:
        replay = await bootstrap_account(
            db,
            claims=claims(subject=subject, email=email),
            idempotency_key=key,
            request_id=f"request-{suffix}",
            correlation_id=f"correlation-{suffix}",
        )
        assert replay == created

        existing = await bootstrap_account(
            db,
            claims=claims(subject=subject, email=email),
            idempotency_key=f"another-{suffix}",
            request_id=f"request-existing-{suffix}",
            correlation_id=f"correlation-existing-{suffix}",
        )
        assert existing.created is False
        assert existing.user_id == created.user_id
        assert existing.organization_id == created.organization_id

        resolved = await resolve_identity(
            db,
            issuer="https://auth.codestra.co/realms/codestra",
            subject=subject,
            requested_organization_id=created.organization_id,
        )
        assert resolved.borrower_id == created.organization_id
        assert "application.read.own" in resolved.permissions

        event = await db.scalar(
            select(models.OutboxEvent).where(
                models.OutboxEvent.idempotency_key == f"account:{created.user_id}"
            )
        )
        assert event is not None
        assert event.event_type == "account.registered.v1"
        encoded_payload = json.dumps(event.payload).lower()
        assert "password" not in encoded_payload
        assert "client_secret" not in encoded_payload

        external = await db.scalar(
            select(identity.ExternalIdentity).where(
                identity.ExternalIdentity.issuer
                == "https://auth.codestra.co/realms/codestra",
                identity.ExternalIdentity.subject == subject,
            )
        )
        assert external is not None
        assert external.email_at_link_time == email


@pytest.mark.asyncio
async def test_verified_email_cannot_bind_to_a_second_subject(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SELF_REGISTRATION_CLIENT_IDS", "moneybee-borrower")
    suffix = uuid.uuid4().hex
    email = f"collision-{suffix}@example.com"

    async with SessionLocal() as db:
        await bootstrap_account(
            db,
            claims=claims(subject=f"first-{suffix}", email=email),
            idempotency_key=f"first-{suffix}",
            request_id=f"request-first-{suffix}",
            correlation_id=f"correlation-first-{suffix}",
        )

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as collision:
            await bootstrap_account(
                db,
                claims=claims(subject=f"second-{suffix}", email=email),
                idempotency_key=f"second-{suffix}",
                request_id=f"request-second-{suffix}",
                correlation_id=f"correlation-second-{suffix}",
            )
        assert collision.value.status_code == 409
        assert collision.value.detail["code"] == "ACCOUNT_LINK_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_unverified_email_and_unapproved_portal_fail_closed(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SELF_REGISTRATION_CLIENT_IDS", "moneybee-borrower")
    suffix = uuid.uuid4().hex

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as unverified:
            await bootstrap_account(
                db,
                claims=claims(
                    subject=f"unverified-{suffix}",
                    email=f"unverified-{suffix}@example.com",
                    verified=False,
                ),
                idempotency_key=f"unverified-{suffix}",
                request_id=f"request-unverified-{suffix}",
                correlation_id=f"correlation-unverified-{suffix}",
            )
        assert getattr(unverified.value, "status_code", None) == 403
        assert unverified.value.detail["code"] == "EMAIL_VERIFICATION_REQUIRED"

        with pytest.raises(HTTPException) as invitation:
            await bootstrap_account(
                db,
                claims=claims(
                    subject=f"lender-{suffix}",
                    email=f"lender-{suffix}@example.com",
                    client_id="moneybee-lender",
                ),
                idempotency_key=f"lender-{suffix}",
                request_id=f"request-lender-{suffix}",
                correlation_id=f"correlation-lender-{suffix}",
            )
        assert getattr(invitation.value, "status_code", None) == 403
        assert invitation.value.detail["code"] == "INVITATION_REQUIRED"
