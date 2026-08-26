from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import identity_models, integration_models, models
from app.auth import Principal, get_current_user
from app.db import get_db
from app.portal_models import PortalNotification, PortalTask
from app.portal_permissions import (
    has_permission,
    require_active_organization,
    require_any_permission,
)
from app.portal_schemas import PortalTaskPatch

router = APIRouter(prefix="/admin", tags=["admin-operations-portal"])


def _json_value(value: Any) -> Any:
    if isinstance(value, (uuid.UUID, datetime, date, Decimal)):
        return str(value)
    return value


def _record(source: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: _json_value(getattr(source, field, None))
        for field in fields
        if hasattr(source, field)
    }


def _first_model(module: Any, *names: str):
    for name in names:
        model = getattr(module, name, None)
        if model is not None:
            return model
    return None


def _first_column(model: Any, *names: str):
    if model is None:
        return None
    for name in names:
        column = getattr(model, name, None)
        if column is not None:
            return column
    return None


def _require_admin(principal: Principal) -> uuid.UUID:
    if "MONEYBEE" not in principal.membership_types:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "MONEYBEE_OPERATIONS_CONTEXT_REQUIRED",
                "message": "An active MoneyBee operations membership is required.",
            },
        )
    return require_active_organization(principal)


def _has_global_scope(principal: Principal) -> bool:
    return has_permission(principal, "capability.manage", "tenant.read.all", "*")


def _count(db: Session, model: Any) -> int:
    if model is None:
        return 0
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _count_by_status(db: Session, model: Any) -> dict[str, int]:
    status_column = _first_column(model, "status", "delivery_status", "processing_status")
    if model is None or status_column is None:
        return {}
    rows = db.execute(
        select(status_column, func.count()).select_from(model).group_by(status_column)
    ).all()
    return {str(state): int(count) for state, count in rows}


def _task_read(task: PortalTask) -> dict[str, Any]:
    return _record(
        task,
        (
            "id",
            "organization_id",
            "application_id",
            "assignee_user_id",
            "created_by_user_id",
            "task_type",
            "title",
            "description",
            "status",
            "priority",
            "due_at",
            "completed_at",
            "version",
            "metadata_payload",
            "created_at",
            "updated_at",
        ),
    )


def _task_statement(principal: Principal):
    statement = select(PortalTask)
    if not _has_global_scope(principal):
        statement = statement.where(
            PortalTask.organization_id == require_active_organization(principal)
        )
    return statement


@router.get("/operations/workspace")
def operations_workspace(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_admin(principal)
    require_any_permission(principal, "lead.read", "capability.read", "*")

    task_statement = _task_statement(principal).where(
        PortalTask.status.in_(("OPEN", "IN_PROGRESS", "BLOCKED"))
    )
    open_tasks = list(
        db.scalars(task_statement.order_by(PortalTask.created_at.desc()).limit(100))
    )

    lead_model = _first_model(models, "Lead")
    application_model = _first_model(models, "Application")
    lender_submission_model = _first_model(models, "LenderSubmission")
    offer_model = _first_model(models, "Offer")
    outbox_model = _first_model(
        integration_models, "OutboxDelivery", "IntegrationOutboxDelivery"
    )
    inbox_model = _first_model(
        integration_models, "IntegrationInboxMessage", "InboxMessage"
    )

    return {
        "principal": {
            "user_id": str(principal.user_id),
            "organization_id": str(require_active_organization(principal)),
            "global_scope": _has_global_scope(principal),
        },
        "metrics": {
            "lead_count": _count(db, lead_model),
            "application_count": _count(db, application_model),
            "lender_submission_count": _count(db, lender_submission_model),
            "offer_count": _count(db, offer_model),
            "open_task_count": len(open_tasks),
        },
        "integration_health": {
            "outbox": _count_by_status(db, outbox_model),
            "inbox": _count_by_status(db, inbox_model),
        },
        "work_queue": [_task_read(item) for item in open_tasks[:25]],
    }


@router.get("/work-queue")
def list_work_queue(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    task_status: str | None = Query(default=None, alias="status", max_length=40),
    priority: str | None = Query(default=None, max_length=20),
    assignee_user_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    _require_admin(principal)
    require_any_permission(principal, "lead.read", "*")
    statement = _task_statement(principal)
    if task_status:
        statement = statement.where(PortalTask.status == task_status.upper())
    if priority:
        statement = statement.where(PortalTask.priority == priority.upper())
    if assignee_user_id:
        statement = statement.where(PortalTask.assignee_user_id == assignee_user_id)
    if application_id:
        statement = statement.where(PortalTask.application_id == application_id)
    items = db.scalars(statement.order_by(PortalTask.created_at.desc()).limit(limit))
    return {"items": [_task_read(item) for item in items]}


@router.patch("/work-queue/{task_id}")
def update_work_queue_item(
    task_id: uuid.UUID,
    payload: PortalTaskPatch,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_admin(principal)
    require_any_permission(principal, "lead.update", "*")
    statement = _task_statement(principal).where(PortalTask.id == task_id)
    task = db.scalar(statement)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Task was not found."},
        )
    if task.version != payload.version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VERSION_CONFLICT",
                "message": "The task changed after it was loaded.",
                "context": {"current_version": task.version},
            },
        )

    previous_assignee = task.assignee_user_id
    if payload.assignee_user_id is not None:
        assignee = db.scalar(
            select(identity_models.User).where(
                identity_models.User.id == payload.assignee_user_id,
                identity_models.User.active.is_(True),
            )
        )
        if assignee is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_ASSIGNEE",
                    "message": "The selected assignee is not an active MoneyBee user.",
                },
            )
        task.assignee_user_id = payload.assignee_user_id
    if payload.status is not None:
        task.status = payload.status
        task.completed_at = (
            datetime.now().astimezone() if payload.status == "COMPLETED" else None
        )
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.due_at is not None:
        task.due_at = payload.due_at
    task.version += 1

    if task.assignee_user_id and task.assignee_user_id != previous_assignee:
        db.add(
            PortalNotification(
                organization_id=task.organization_id,
                user_id=task.assignee_user_id,
                notification_type="TASK_ASSIGNED",
                title="A task was assigned to you",
                body=task.title,
                action_url=f"/work-queue/{task.id}",
                metadata_payload={"task_id": str(task.id)},
            )
        )
    db.commit()
    db.refresh(task)
    return _task_read(task)


def _search_model(
    db: Session,
    model: Any,
    *,
    kind: str,
    query: str,
    label_columns: tuple[str, ...],
    status_columns: tuple[str, ...] = ("status",),
    limit: int,
) -> list[dict[str, Any]]:
    if model is None:
        return []
    columns = [
        getattr(model, name)
        for name in label_columns
        if getattr(model, name, None) is not None
    ]
    if not columns:
        return []
    rows = db.scalars(
        select(model)
        .where(or_(*(column.ilike(f"%{query}%") for column in columns)))
        .limit(limit)
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        label = next(
            (
                str(getattr(row, name))
                for name in label_columns
                if getattr(row, name, None)
            ),
            str(getattr(row, "id", "")),
        )
        state = next(
            (
                str(getattr(row, name))
                for name in status_columns
                if getattr(row, name, None) is not None
            ),
            None,
        )
        results.append(
            {
                "type": kind,
                "id": str(getattr(row, "id")),
                "label": label,
                "status": state,
            }
        )
    return results


@router.get("/search")
def global_operations_search(
    q: str = Query(min_length=2, max_length=120),
    principal: Annotated[Principal, Depends(get_current_user)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
    limit_per_type: int = Query(default=10, ge=1, le=25),
):
    _require_admin(principal)
    require_any_permission(principal, "lead.read", "*")
    normalized = q.strip()
    results: list[dict[str, Any]] = []
    results.extend(
        _search_model(
            db,
            _first_model(models, "Lead"),
            kind="lead",
            query=normalized,
            label_columns=("business_name", "company_name", "contact_name", "name"),
            limit=limit_per_type,
        )
    )
    results.extend(
        _search_model(
            db,
            _first_model(models, "Application"),
            kind="application",
            query=normalized,
            label_columns=("application_number", "business_name", "name"),
            limit=limit_per_type,
        )
    )
    results.extend(
        _search_model(
            db,
            _first_model(models, "Borrower"),
            kind="borrower",
            query=normalized,
            label_columns=("business_name", "legal_name", "display_name"),
            limit=limit_per_type,
        )
    )
    results.extend(
        _search_model(
            db,
            _first_model(models, "Lender"),
            kind="lender",
            query=normalized,
            label_columns=("name", "legal_name", "display_name"),
            limit=limit_per_type,
        )
    )
    return {"query": normalized, "items": results}


@router.get("/audit-events")
def list_audit_events(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    _require_admin(principal)
    require_any_permission(principal, "capability.read", "audit.read", "*")
    audit_model = _first_model(models, "AuditEvent", "AuditLog", "AuditRecord")
    if audit_model is None:
        return {"items": [], "next_before": None}

    statement = select(audit_model)
    organization_column = _first_column(audit_model, "organization_id", "tenant_id")
    created_column = _first_column(audit_model, "created_at", "occurred_at")
    if organization_column is not None and not _has_global_scope(principal):
        statement = statement.where(
            organization_column == require_active_organization(principal)
        )
    if before is not None and created_column is not None:
        statement = statement.where(created_column < before)
    if created_column is not None:
        statement = statement.order_by(created_column.desc())
    rows = list(db.scalars(statement.limit(limit)))
    items = [
        _record(
            row,
            (
                "id",
                "organization_id",
                "actor_user_id",
                "action",
                "event_type",
                "resource_type",
                "resource_id",
                "correlation_id",
                "request_id",
                "created_at",
                "occurred_at",
            ),
        )
        for row in rows
    ]
    next_before = None
    if rows and created_column is not None:
        next_before = _json_value(getattr(rows[-1], created_column.key, None))
    return {"items": items, "next_before": next_before}


@router.get("/organizations")
def list_organizations(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    organization_type: str | None = Query(default=None, max_length=40),
    active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    _require_admin(principal)
    require_any_permission(principal, "capability.read", "*")
    statement = select(identity_models.Organization)
    if organization_type:
        statement = statement.where(
            identity_models.Organization.organization_type == organization_type.upper()
        )
    if active is not None:
        statement = statement.where(identity_models.Organization.active.is_(active))
    organizations = db.scalars(
        statement.order_by(identity_models.Organization.name).limit(limit)
    )
    return {
        "items": [
            _record(
                item,
                ("id", "name", "organization_type", "active", "created_at", "updated_at"),
            )
            for item in organizations
        ]
    }


@router.get("/organizations/{organization_id}/members")
def list_organization_members(
    organization_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_admin(principal)
    require_any_permission(principal, "capability.read", "*")
    membership_model = identity_models.OrganizationMembership
    rows = db.execute(
        select(membership_model, identity_models.User)
        .join(identity_models.User, identity_models.User.id == membership_model.user_id)
        .where(membership_model.organization_id == organization_id)
        .order_by(identity_models.User.display_name)
    ).all()
    return {
        "items": [
            {
                "membership": _record(
                    membership,
                    (
                        "organization_id",
                        "user_id",
                        "membership_type",
                        "active",
                        "created_at",
                    ),
                ),
                "user": _record(
                    user,
                    ("id", "display_name", "active", "created_at", "updated_at"),
                ),
            }
            for membership, user in rows
        ]
    }


@router.get("/integration-health")
def integration_health(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_admin(principal)
    require_any_permission(principal, "capability.read", "*")
    outbox_model = _first_model(
        integration_models, "OutboxDelivery", "IntegrationOutboxDelivery"
    )
    inbox_model = _first_model(
        integration_models, "IntegrationInboxMessage", "InboxMessage"
    )
    return {
        "outbox": {
            "total": _count(db, outbox_model),
            "by_status": _count_by_status(db, outbox_model),
        },
        "inbox": {
            "total": _count(db, inbox_model),
            "by_status": _count_by_status(db, inbox_model),
        },
    }
