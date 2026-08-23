from dataclasses import dataclass
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import identity_models as identity


@dataclass(frozen=True)
class ResolvedIdentity:
    user_id: uuid.UUID
    issuer: str
    subject: str
    organization_ids: tuple[uuid.UUID, ...]
    active_organization_id: uuid.UUID
    roles: frozenset[str]
    permissions: frozenset[str]
    membership_types: frozenset[str]
    borrower_id: uuid.UUID | None
    lender_id: uuid.UUID | None
    is_active: bool


class IdentityResolutionError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _uuid(value: str | uuid.UUID | None, *, code: str) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError as exc:
        raise IdentityResolutionError(
            code,
            "The organization selection is invalid.",
            403,
        ) from exc


async def resolve_identity(
    db: AsyncSession,
    *,
    issuer: str,
    subject: str,
    requested_organization_id: str | uuid.UUID | None,
) -> ResolvedIdentity:
    external = await db.scalar(
        select(identity.ExternalIdentity).where(
            identity.ExternalIdentity.issuer == issuer,
            identity.ExternalIdentity.subject == subject,
        )
    )
    if external is None:
        raise IdentityResolutionError(
            "IDENTITY_NOT_BOUND",
            "The authenticated identity is not bound to MoneyBee.",
            401,
        )
    user = await db.get(identity.User, external.user_id)
    if user is None:
        raise IdentityResolutionError(
            "IDENTITY_NOT_BOUND", "The local MoneyBee user does not exist.", 401
        )
    if not user.active:
        raise IdentityResolutionError(
            "USER_DISABLED", "The local MoneyBee user is disabled.", 403
        )

    memberships = list(
        (
            await db.scalars(
                select(identity.OrganizationMembership).where(
                    identity.OrganizationMembership.user_id == user.id,
                    identity.OrganizationMembership.active.is_(True),
                )
            )
        ).all()
    )
    if not memberships:
        raise IdentityResolutionError(
            "MEMBERSHIP_INACTIVE",
            "The local MoneyBee user has no active organization membership.",
            403,
        )

    organizations = {
        row.id: row
        for row in (
            await db.scalars(
                select(identity.Organization).where(
                    identity.Organization.id.in_(
                        [item.organization_id for item in memberships]
                    ),
                    identity.Organization.active.is_(True),
                )
            )
        ).all()
    }
    valid_memberships = [
        item for item in memberships if item.organization_id in organizations
    ]
    organization_ids = tuple(
        sorted({item.organization_id for item in valid_memberships}, key=str)
    )
    if not organization_ids:
        raise IdentityResolutionError(
            "MEMBERSHIP_INACTIVE",
            "The organization membership is inactive.",
            403,
        )

    requested = _uuid(requested_organization_id, code="TENANT_ACCESS_DENIED")
    if requested is None:
        if len(organization_ids) != 1:
            raise IdentityResolutionError(
                "TENANT_SELECTION_REQUIRED",
                "An active organization must be selected.",
                403,
            )
        active_organization_id = organization_ids[0]
    elif requested not in organization_ids:
        raise IdentityResolutionError(
            "TENANT_ACCESS_DENIED",
            "The user does not belong to the selected organization.",
            403,
        )
    else:
        active_organization_id = requested

    active_memberships = [
        item
        for item in valid_memberships
        if item.organization_id == active_organization_id
    ]
    membership_types = frozenset(item.membership_type for item in active_memberships)

    bindings = list(
        (
            await db.scalars(
                select(identity.UserRoleBinding).where(
                    identity.UserRoleBinding.user_id == user.id,
                    identity.UserRoleBinding.organization_id == active_organization_id,
                    identity.UserRoleBinding.active.is_(True),
                )
            )
        ).all()
    )
    role_ids = [binding.role_id for binding in bindings]
    roles = frozenset()
    permissions = frozenset()
    if role_ids:
        active_roles = list(
            (
                await db.execute(
                    select(identity.Role.id, identity.Role.code).where(
                        identity.Role.id.in_(role_ids),
                        identity.Role.active.is_(True),
                    )
                )
            ).all()
        )
        active_role_ids = [row.id for row in active_roles]
        roles = frozenset(row.code for row in active_roles)
        if active_role_ids:
            permissions = frozenset(
                await db.scalars(
                    select(identity.Permission.code)
                    .join(
                        identity.RolePermission,
                        identity.RolePermission.permission_id
                        == identity.Permission.id,
                    )
                    .where(identity.RolePermission.role_id.in_(active_role_ids))
                )
            )

    return ResolvedIdentity(
        user_id=user.id,
        issuer=issuer,
        subject=subject,
        organization_ids=organization_ids,
        active_organization_id=active_organization_id,
        roles=roles,
        permissions=permissions,
        membership_types=membership_types,
        borrower_id=(
            active_organization_id if "BORROWER" in membership_types else None
        ),
        lender_id=(active_organization_id if "LENDER" in membership_types else None),
        is_active=True,
    )
