from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import NoReturn

from fastapi import HTTPException

from app.auth import Principal


def problem(code: str, message: str, status_code: int = 400) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def active_organization(user: Principal, membership_type: str) -> uuid.UUID | None:
    if "*" in user.permissions:
        return user.active_organization_id
    if membership_type == "BORROWER" and user.borrower_id:
        return user.borrower_id
    if membership_type == "LENDER" and user.lender_id:
        return user.lender_id
    if membership_type in user.membership_types and user.active_organization_id:
        return user.active_organization_id
    problem(
        "RESOURCE_ACCESS_DENIED",
        f"An active {membership_type.lower()} organization membership is required.",
        403,
    )


def require_any_permission(user: Principal, *permissions: str) -> None:
    if "*" in user.permissions or any(item in user.permissions for item in permissions):
        return
    problem("PERMISSION_DENIED", "The principal does not have the required permission.", 403)


def actor_type(user: Principal) -> str:
    if "BORROWER" in user.membership_types:
        return "BORROWER"
    if "LENDER" in user.membership_types:
        return "LENDER"
    if "MONEYBEE" in user.membership_types or "*" in user.permissions:
        return "ADMIN"
    if "AFFILIATE" in user.membership_types:
        return "AFFILIATE"
    return "UNKNOWN"


def completed_at(status: str) -> datetime | None:
    return datetime.now(UTC) if status == "COMPLETED" else None
