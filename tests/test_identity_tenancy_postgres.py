from decimal import Decimal
import os
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import identity_models as identity
from app import models
from app.auth import Principal, require_permission
from app.identity import IdentityResolutionError, resolve_identity
from app.routers import authorized_submission
from app.services import authorize_application


DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql+asyncpg://"),
    reason="PostgreSQL authorization persistence test",
)


def principal_from(resolved) -> Principal:
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


async def create_bound_identity(
    db: AsyncSession,
    *,
    subject: str,
    membership_type: str,
    permission_code: str,
) -> tuple[identity.User, identity.Organization, identity.OrganizationMembership]:
    suffix = uuid.uuid4().hex
    user = identity.User(email=f"{suffix}@example.test", active=True)
    organization = identity.Organization(
        name=f"Test {membership_type} {suffix}",
        organization_type=membership_type,
        active=True,
    )
    db.add_all([user, organization])
    await db.flush()
    membership = identity.OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        membership_type=membership_type,
        active=True,
    )
    role = identity.Role(code=f"TEST_{membership_type}_{suffix}", active=True)
    permission = await db.scalar(
        select(identity.Permission).where(identity.Permission.code == permission_code)
    )
    if permission is None:
        permission = identity.Permission(code=permission_code)
        db.add(permission)
    db.add_all(
        [
            identity.ExternalIdentity(
                user_id=user.id,
                issuer="https://auth.codestra.co/realms/codestra",
                subject=subject,
            ),
            membership,
            role,
        ]
    )
    await db.flush()
    db.add_all(
        [
            identity.RolePermission(role_id=role.id, permission_id=permission.id),
            identity.UserRoleBinding(
                user_id=user.id,
                role_id=role.id,
                organization_id=organization.id,
                active=True,
            ),
        ]
    )
    await db.commit()
    return user, organization, membership


@pytest.mark.asyncio
async def test_postgres_identity_binding_tenant_and_negative_authorization():
    engine = create_async_engine(DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    borrower_subject = f"borrower-{uuid.uuid4()}"
    lender_subject = f"lender-{uuid.uuid4()}"

    async with session_factory() as db:
        with pytest.raises(IdentityResolutionError) as unknown:
            await resolve_identity(
                db,
                issuer="https://auth.codestra.co/realms/codestra",
                subject=f"unknown-{uuid.uuid4()}",
                requested_organization_id=None,
            )
        assert unknown.value.code == "IDENTITY_NOT_BOUND"

        borrower_user, borrower_org, borrower_membership = await create_bound_identity(
            db,
            subject=borrower_subject,
            membership_type="BORROWER",
            permission_code="application.read.own",
        )
        resolved_borrower = await resolve_identity(
            db,
            issuer="https://auth.codestra.co/realms/codestra",
            subject=borrower_subject,
            requested_organization_id=borrower_org.id,
        )
        borrower = principal_from(resolved_borrower)
        assert borrower.borrower_id == borrower_org.id
        assert borrower.permissions == frozenset({"application.read.own"})

        with pytest.raises(IdentityResolutionError) as wrong_tenant:
            await resolve_identity(
                db,
                issuer="https://auth.codestra.co/realms/codestra",
                subject=borrower_subject,
                requested_organization_id=uuid.uuid4(),
            )
        assert wrong_tenant.value.code == "TENANT_ACCESS_DENIED"

        other_application = models.Application(
            lead_id=uuid.uuid4(),
            borrower_subject="another-subject",
            borrower_organization_id=uuid.uuid4(),
            requested_amount=Decimal("10000"),
            monthly_revenue=Decimal("25000"),
            time_in_business_months=24,
        )
        with pytest.raises(HTTPException) as borrower_denied:
            authorize_application(other_application, borrower)
        assert borrower_denied.value.detail["code"] == "RESOURCE_ACCESS_DENIED"

        borrower_membership.active = False
        await db.commit()
        with pytest.raises(IdentityResolutionError) as inactive_membership:
            await resolve_identity(
                db,
                issuer="https://auth.codestra.co/realms/codestra",
                subject=borrower_subject,
                requested_organization_id=borrower_org.id,
            )
        assert inactive_membership.value.code == "MEMBERSHIP_INACTIVE"
        borrower_membership.active = True
        borrower_user.active = False
        await db.commit()
        with pytest.raises(IdentityResolutionError) as disabled_user:
            await resolve_identity(
                db,
                issuer="https://auth.codestra.co/realms/codestra",
                subject=borrower_subject,
                requested_organization_id=borrower_org.id,
            )
        assert disabled_user.value.code == "USER_DISABLED"

        _, lender_org, _ = await create_bound_identity(
            db,
            subject=lender_subject,
            membership_type="LENDER",
            permission_code="lender.submission.read",
        )
        resolved_lender = await resolve_identity(
            db,
            issuer="https://auth.codestra.co/realms/codestra",
            subject=lender_subject,
            requested_organization_id=lender_org.id,
        )
        lender = principal_from(resolved_lender)

        class FakeDb:
            async def get(self, model, identifier):
                return SimpleNamespace(lender_id=uuid.uuid4())

        with pytest.raises(HTTPException) as lender_denied:
            await authorized_submission(uuid.uuid4(), FakeDb(), lender)
        assert lender_denied.value.status_code == 403

        permission_dependency = require_permission("admin.only")
        with pytest.raises(HTTPException) as staff_denied:
            await permission_dependency(borrower)
        assert staff_denied.value.detail["code"] == "PERMISSION_DENIED"

    await engine.dispose()
