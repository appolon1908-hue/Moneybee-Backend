from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.auth import Principal


@dataclass(frozen=True)
class PortalNavigationItem:
    key: str
    label: str
    path: str
    memberships: frozenset[str] = frozenset()
    permissions: frozenset[str] = frozenset()


NAVIGATION: tuple[PortalNavigationItem, ...] = (
    PortalNavigationItem(
        key="borrower.dashboard",
        label="Overview",
        path="/dashboard",
        memberships=frozenset({"BORROWER"}),
    ),
    PortalNavigationItem(
        key="borrower.application",
        label="Application",
        path="/application",
        memberships=frozenset({"BORROWER"}),
        permissions=frozenset({"application.read.own"}),
    ),
    PortalNavigationItem(
        key="borrower.documents",
        label="Documents",
        path="/documents",
        memberships=frozenset({"BORROWER"}),
    ),
    PortalNavigationItem(
        key="borrower.messages",
        label="Messages",
        path="/messages",
        memberships=frozenset({"BORROWER"}),
    ),
    PortalNavigationItem(
        key="borrower.offers",
        label="Offers",
        path="/offers",
        memberships=frozenset({"BORROWER"}),
        permissions=frozenset({"application.read.own"}),
    ),
    PortalNavigationItem(
        key="lender.dashboard",
        label="Portfolio",
        path="/dashboard",
        memberships=frozenset({"LENDER"}),
    ),
    PortalNavigationItem(
        key="lender.submissions",
        label="Submissions",
        path="/applications",
        memberships=frozenset({"LENDER"}),
        permissions=frozenset({"lender.submission.read"}),
    ),
    PortalNavigationItem(
        key="lender.programs",
        label="Programs",
        path="/programs",
        memberships=frozenset({"LENDER"}),
        permissions=frozenset({"program.manage"}),
    ),
    PortalNavigationItem(
        key="lender.offers",
        label="Offers",
        path="/offers",
        memberships=frozenset({"LENDER"}),
        permissions=frozenset({"offer.create"}),
    ),
    PortalNavigationItem(
        key="admin.operations",
        label="Operations",
        path="/operations",
        memberships=frozenset({"MONEYBEE"}),
        permissions=frozenset({"lead.read"}),
    ),
    PortalNavigationItem(
        key="admin.work_queue",
        label="Work queue",
        path="/work-queue",
        memberships=frozenset({"MONEYBEE"}),
        permissions=frozenset({"lead.read"}),
    ),
    PortalNavigationItem(
        key="admin.audit",
        label="Audit",
        path="/audit",
        memberships=frozenset({"MONEYBEE"}),
        permissions=frozenset({"capability.read"}),
    ),
    PortalNavigationItem(
        key="admin.integrations",
        label="Integrations",
        path="/integration-inbox",
        memberships=frozenset({"MONEYBEE"}),
        permissions=frozenset({"capability.read"}),
    ),
)


def has_permission(principal: Principal, *permissions: str) -> bool:
    if "*" in principal.permissions:
        return True
    return any(permission in principal.permissions for permission in permissions)


def require_any_permission(principal: Principal, *permissions: str) -> None:
    if has_permission(principal, *permissions):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "PERMISSION_DENIED",
            "message": "The principal does not have the required portal permission.",
            "context": {"required_permissions": list(permissions)},
        },
    )


def require_active_organization(principal: Principal):
    if principal.active_organization_id is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TENANT_SELECTION_REQUIRED",
                "message": "An active organization must be selected.",
            },
        )
    return principal.active_organization_id


def build_navigation(principal: Principal) -> list[dict[str, Any]]:
    navigation: list[dict[str, Any]] = []
    for item in NAVIGATION:
        membership_allowed = (
            not item.memberships
            or bool(item.memberships.intersection(principal.membership_types))
        )
        permission_allowed = (
            not item.permissions
            or "*" in principal.permissions
            or bool(item.permissions.intersection(principal.permissions))
        )
        if membership_allowed and permission_allowed:
            navigation.append(
                {
                    "key": item.key,
                    "label": item.label,
                    "path": item.path,
                }
            )
    return navigation
