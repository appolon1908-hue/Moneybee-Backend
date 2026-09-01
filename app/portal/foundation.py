from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import identity_models, schemas as application_schemas, services
from app.auth import Principal, current_principal
from app.db import get_db
from app.portal.common import actor_type
from app.portal.schemas import NavigationItem, PortalContext, PortalOrganization


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


def principal_read(user: Principal) -> application_schemas.PrincipalRead:
    return application_schemas.PrincipalRead(
        user_id=user.user_id,
        issuer=user.issuer,
        subject=user.subject,
        organization_ids=list(user.organization_ids),
        active_organization_id=user.active_organization_id,
        roles=sorted(user.roles),
        permissions=sorted(user.permissions),
        membership_types=sorted(user.membership_types),
        borrower_id=user.borrower_id,
        lender_id=user.lender_id,
        is_active=user.is_active,
    )


@router.get(
    "/auth/me",
    response_model=application_schemas.PrincipalRead,
    tags=["identity", "portal"],
)
async def auth_me(user: User):
    """Canonical portal identity alias backed by local MoneyBee authorization."""
    return principal_read(user)


@router.get(
    "/auth/context",
    response_model=PortalContext,
    tags=["identity", "portal"],
)
async def auth_context(db: Db, user: User, request: Request):
    await services.record_login_event(
        db,
        user_id=user.user_id,
        issuer=user.issuer,
        subject=user.subject,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    organizations: list[identity_models.Organization] = []
    if user.organization_ids:
        organizations = list(
            (
                await db.scalars(
                    select(identity_models.Organization)
                    .where(
                        identity_models.Organization.id.in_(user.organization_ids),
                        identity_models.Organization.active.is_(True),
                    )
                    .order_by(identity_models.Organization.name)
                )
            ).all()
        )
    return PortalContext(
        user_id=user.user_id,
        subject=user.subject,
        active_organization_id=user.active_organization_id,
        organizations=[
            PortalOrganization(
                id=item.id,
                name=item.name,
                organization_type=item.organization_type,
            )
            for item in organizations
        ],
        roles=sorted(user.roles),
        permissions=sorted(user.permissions),
        membership_types=sorted(user.membership_types),
        portal=actor_type(user),
        capabilities=await services.effective_capabilities(db),
    )


def _allowed(user: Principal, permission: str | None) -> bool:
    return permission is None or "*" in user.permissions or permission in user.permissions


@router.get(
    "/portal/navigation",
    response_model=list[NavigationItem],
    tags=["portal"],
)
async def portal_navigation(user: User):
    portal = actor_type(user)
    catalog: dict[str, list[NavigationItem]] = {
        "BORROWER": [
            NavigationItem(key="dashboard", label="Dashboard", path="/dashboard", group="Workspace"),
            NavigationItem(key="application", label="Application", path="/application", group="Funding"),
            NavigationItem(key="documents", label="Documents", path="/documents", group="Funding"),
            NavigationItem(key="banking", label="Banking", path="/banking", group="Funding"),
            NavigationItem(key="conditions", label="Conditions", path="/conditions", group="Funding"),
            NavigationItem(key="offers", label="Offers", path="/offers", group="Funding"),
            NavigationItem(key="tasks", label="Tasks", path="/tasks", group="Workspace"),
            NavigationItem(key="messages", label="Messages", path="/messages", group="Workspace"),
            NavigationItem(key="notifications", label="Notifications", path="/notifications", group="Workspace"),
            NavigationItem(key="support", label="Support", path="/support", group="Account"),
        ],
        "LENDER": [
            NavigationItem(key="dashboard", label="Dashboard", path="/dashboard", group="Workspace"),
            NavigationItem(
                key="applications",
                label="Application queue",
                path="/applications",
                group="Underwriting",
                required_permission="lender.submission.read",
            ),
            NavigationItem(key="programs", label="Programs", path="/programs", group="Configuration"),
            NavigationItem(key="offers", label="Offers", path="/offers", group="Underwriting"),
            NavigationItem(key="bank-review", label="Bank review", path="/bank-review", group="Underwriting"),
            NavigationItem(key="funded", label="Funded deals", path="/funded-deals", group="Portfolio"),
        ],
        "ADMIN": [
            NavigationItem(key="dashboard", label="Dashboard", path="/dashboard", group="Operations"),
            NavigationItem(key="applications", label="Applications", path="/applications", group="Lending", required_permission="application.read"),
            NavigationItem(key="underwriting", label="Underwriting", path="/underwriting", group="Lending", required_permission="underwriting.review"),
            NavigationItem(key="operations", label="Operations", path="/operations", group="Operations", required_permission="lead.read"),
            NavigationItem(key="tasks", label="Task queue", path="/tasks", group="Operations", required_permission="lead.read"),
            NavigationItem(key="conversations", label="Conversations", path="/conversations", group="Service", required_permission="lead.read"),
            NavigationItem(key="audit", label="Audit", path="/audit", group="Governance", required_permission="capability.read"),
            NavigationItem(key="webhooks", label="Webhooks", path="/webhooks", group="Integrations", required_permission="capability.read"),
            NavigationItem(key="system", label="System", path="/system", group="Governance", required_permission="capability.read"),
        ],
    }
    key = "ADMIN" if portal == "MONEYBEE" or "*" in user.permissions else portal
    return [item for item in catalog.get(key, []) if _allowed(user, item.required_permission)]
