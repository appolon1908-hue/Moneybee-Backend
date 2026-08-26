import uuid
from collections.abc import Iterable

from fastapi import HTTPException

from app.auth import Principal


def problem(code: str, message: str, status_code: int = 403) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def active_tenant(principal: Principal) -> uuid.UUID:
    tenant_id = principal.active_organization_id
    if tenant_id is None:
        raise problem(
            "TENANT_SELECTION_REQUIRED",
            "An active organization must be selected.",
        )
    return tenant_id


def has_any_permission(principal: Principal, permissions: Iterable[str]) -> bool:
    expected = set(permissions)
    return "*" in principal.permissions or bool(expected.intersection(principal.permissions))


def is_moneybee_admin(principal: Principal) -> bool:
    return (
        "*" in principal.permissions
        or "MONEYBEE" in principal.membership_types
        or any(role.startswith("MONEYBEE_") for role in principal.roles)
    )


def require_moneybee_admin(principal: Principal) -> None:
    if not is_moneybee_admin(principal):
        raise problem(
            "ADMIN_MEMBERSHIP_REQUIRED",
            "An active MoneyBee administrative membership is required.",
        )


def require_borrower(principal: Principal) -> uuid.UUID:
    if principal.borrower_id is None or "BORROWER" not in principal.membership_types:
        raise problem(
            "BORROWER_MEMBERSHIP_REQUIRED",
            "An active borrower membership is required.",
        )
    return principal.borrower_id


def require_lender(principal: Principal) -> uuid.UUID:
    if principal.lender_id is None or "LENDER" not in principal.membership_types:
        raise problem(
            "LENDER_MEMBERSHIP_REQUIRED",
            "An active lender membership is required.",
        )
    return principal.lender_id


def ensure_tenant_access(principal: Principal, tenant_id: uuid.UUID) -> None:
    if is_moneybee_admin(principal):
        return
    if tenant_id != active_tenant(principal):
        raise problem(
            "RESOURCE_ACCESS_DENIED",
            "The selected organization does not own this resource.",
        )


def ensure_subject_or_admin(principal: Principal, subject: str | None) -> None:
    if is_moneybee_admin(principal):
        return
    if subject != principal.subject:
        raise problem(
            "RESOURCE_ACCESS_DENIED",
            "The authenticated user is not assigned to this resource.",
        )


def ensure_conversation_access(
    principal: Principal,
    *,
    tenant_id: uuid.UUID,
    participant_subjects: list[str],
) -> None:
    ensure_tenant_access(principal, tenant_id)
    if is_moneybee_admin(principal):
        return
    if principal.subject not in participant_subjects:
        raise problem(
            "CONVERSATION_ACCESS_DENIED",
            "The authenticated user is not a conversation participant.",
        )
