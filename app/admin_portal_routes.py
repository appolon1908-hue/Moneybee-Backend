import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import identity_models, models
from app.auth import User, get_current_user
from app.db import get_db
from app.portal_models import PortalNotification, PortalTask
from app.portal_security import active_tenant, require_moneybee_admin

router = APIRouter(prefix="/admin", tags=["admin-operations-portal"])


class AdminTaskCreate(BaseModel):
    tenant_id: uuid.UUID
    application_id: uuid.UUID | None = None
    task_type: str = Field(default="OPERATIONS", min_length=2, max_length=80)
    title: str = Field(min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"
    assigned_to_subject: str | None = Field(default=None, max_length=255)
    due_at: datetime | None = None
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


class AdminTaskPatch(BaseModel):
    expected_version: int = Field(ge=1)
    status: Literal["OPEN", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"] | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] | None = None
    assigned_to_subject: str | None = Field(default=None, max_length=255)
    due_at: datetime | None = None
    description: str | None = Field(default=None, max_length=10_000)


class AdminNotificationCreate(BaseModel):
    tenant_id: uuid.UUID
    recipient_subject: str = Field(min_length=1, max_length=255)
    notification_type: str = Field(default="OPERATIONS", min_length=2, max_length=80)
    title: str = Field(min_length=2, max_length=240)
    body: str = Field(min_length=1, max_length=10_000)
    href: str | None = Field(default=None, max_length=1000)
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


ALLOWED_TASK_TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"},
    "IN_PROGRESS": {"OPEN", "BLOCKED", "COMPLETED", "CANCELLED"},
    "BLOCKED": {"OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"},
    "COMPLETED": {"OPEN"},
    "CANCELLED": {"OPEN"},
}


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return value


def _public(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: _iso(getattr(row, field, None))
        for field in fields
        if hasattr(row, field)
    }


def _construct(model: type, values: dict[str, Any]) -> Any:
    columns = {column.name for column in model.__table__.columns}
    return model(**{key: value for key, value in values.items() if key in columns})


def _audit(
    *,
    user: User,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    details: dict[str, Any],
) -> Any:
    return _construct(
        models.AuditEvent,
        {
            "actor_subject": user.principal.subject,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": {
                **details,
                "active_organization_id": str(active_tenant(user.principal)),
                "user_id": str(user.principal.user_id),
            },
        },
    )


async def _count(db: AsyncSession, model: type, *conditions: Any) -> int:
    query = select(func.count()).select_from(model)
    if conditions:
        query = query.where(*conditions)
    return int((await db.execute(query)).scalar_one())


@router.get("/operations/workspace")
async def operations_workspace(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    require_moneybee_admin(user.principal)
    open_task_statuses = ["OPEN", "IN_PROGRESS", "BLOCKED"]
    open_tasks = await _count(db, PortalTask, PortalTask.status.in_(open_task_statuses))
    urgent_tasks = await _count(
        db,
        PortalTask,
        PortalTask.status.in_(open_task_statuses),
        PortalTask.priority == "URGENT",
    )
    applications = await _count(db, models.Application)
    active_applications = await _count(
        db,
        models.Application,
        models.Application.status.notin_(["FUNDED", "DECLINED", "WITHDRAWN", "EXPIRED"]),
    )
    lender_submissions = await _count(db, models.LenderSubmission)
    pending_submissions = await _count(
        db,
        models.LenderSubmission,
        models.LenderSubmission.status.notin_(["APPROVED", "DECLINED", "WITHDRAWN", "EXPIRED"]),
    )
    open_exceptions = await _count(
        db,
        models.OperationalException,
        models.OperationalException.status.in_(["OPEN", "RETRY", "BLOCKED"]),
    )
    work_result = await db.execute(
        select(PortalTask)
        .where(PortalTask.status.in_(open_task_statuses))
        .order_by(
            PortalTask.priority.desc(),
            PortalTask.due_at.asc(),
            PortalTask.created_at.asc(),
        )
        .limit(50)
    )
    exception_result = await db.execute(
        select(models.OperationalException)
        .where(models.OperationalException.status.in_(["OPEN", "RETRY", "BLOCKED"]))
        .order_by(models.OperationalException.created_at.desc())
        .limit(25)
    )
    return {
        "metrics": {
            "applications": applications,
            "active_applications": active_applications,
            "lender_submissions": lender_submissions,
            "pending_lender_submissions": pending_submissions,
            "open_tasks": open_tasks,
            "urgent_tasks": urgent_tasks,
            "open_operational_exceptions": open_exceptions,
        },
        "work_queue": [
            _public(
                task,
                (
                    "id",
                    "tenant_id",
                    "application_id",
                    "task_type",
                    "title",
                    "status",
                    "priority",
                    "assigned_to_subject",
                    "due_at",
                    "version",
                    "created_at",
                ),
            )
            for task in work_result.scalars().all()
        ],
        "operational_exceptions": [
            _public(
                exception,
                (
                    "id",
                    "exception_type",
                    "severity",
                    "status",
                    "provider",
                    "entity_type",
                    "entity_id",
                    "message",
                    "attempts",
                    "last_error",
                    "created_at",
                    "updated_at",
                ),
            )
            for exception in exception_result.scalars().all()
        ],
    }


@router.get("/tasks")
async def admin_list_tasks(
    tenant_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    status: str | None = None,
    priority: str | None = None,
    assigned_to_subject: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    require_moneybee_admin(user.principal)
    query = select(PortalTask)
    if tenant_id:
        query = query.where(PortalTask.tenant_id == tenant_id)
    if application_id:
        query = query.where(PortalTask.application_id == application_id)
    if status:
        query = query.where(PortalTask.status == status.upper())
    if priority:
        query = query.where(PortalTask.priority == priority.upper())
    if assigned_to_subject:
        query = query.where(PortalTask.assigned_to_subject == assigned_to_subject)
    result = await db.execute(
        query.order_by(
            PortalTask.priority.desc(),
            PortalTask.due_at.asc(),
            PortalTask.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return [
        _public(
            task,
            (
                "id",
                "tenant_id",
                "application_id",
                "task_type",
                "title",
                "description",
                "status",
                "priority",
                "assigned_to_subject",
                "created_by_subject",
                "due_at",
                "completed_at",
                "version",
                "metadata_payload",
                "created_at",
                "updated_at",
            ),
        )
        for task in result.scalars().all()
    ]


@router.post("/tasks", status_code=201)
async def admin_create_task(
    payload: AdminTaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    require_moneybee_admin(user.principal)
    organization = await db.get(identity_models.Organization, payload.tenant_id)
    if organization is None or not bool(getattr(organization, "active", True)):
        raise _problem(
            "ORGANIZATION_NOT_FOUND",
            "An active organization is required for this task.",
            404,
        )
    if payload.application_id and await db.get(models.Application, payload.application_id) is None:
        raise _problem("APPLICATION_NOT_FOUND", "Application was not found.", 404)
    task = PortalTask(
        tenant_id=payload.tenant_id,
        application_id=payload.application_id,
        task_type=payload.task_type.upper(),
        title=payload.title.strip(),
        description=payload.description,
        priority=payload.priority,
        assigned_to_subject=payload.assigned_to_subject,
        created_by_subject=user.principal.subject,
        due_at=payload.due_at,
        metadata_payload=payload.metadata_payload,
    )
    db.add(task)
    await db.flush()
    db.add(
        _audit(
            user=user,
            action="admin_portal_task.created",
            entity_type="portal_task",
            entity_id=task.id,
            details={
                "tenant_id": str(task.tenant_id),
                "application_id": str(task.application_id or ""),
                "assigned_to_subject": task.assigned_to_subject,
            },
        )
    )
    if task.assigned_to_subject:
        db.add(
            PortalNotification(
                tenant_id=task.tenant_id,
                recipient_subject=task.assigned_to_subject,
                notification_type="TASK_ASSIGNED",
                title=task.title,
                body=task.description or "A MoneyBee task was assigned to you.",
                href=(
                    f"/applications/{task.application_id}"
                    if task.application_id
                    else "/tasks"
                ),
                metadata_payload={"task_id": str(task.id), "priority": task.priority},
            )
        )
    await db.commit()
    await db.refresh(task)
    return _public(
        task,
        (
            "id",
            "tenant_id",
            "application_id",
            "task_type",
            "title",
            "description",
            "status",
            "priority",
            "assigned_to_subject",
            "due_at",
            "version",
            "created_at",
        ),
    )


@router.patch("/tasks/{task_id}")
async def admin_update_task(
    task_id: uuid.UUID,
    payload: AdminTaskPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    require_moneybee_admin(user.principal)
    result = await db.execute(
        select(PortalTask).where(PortalTask.id == task_id).with_for_update()
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise _problem("PORTAL_TASK_NOT_FOUND", "Portal task was not found.", 404)
    if task.version != payload.expected_version:
        raise _problem(
            "RESOURCE_VERSION_CONFLICT",
            "The portal task was modified by another request.",
            409,
        )
    previous_status = task.status
    previous_assignee = task.assigned_to_subject
    if payload.status is not None:
        allowed = ALLOWED_TASK_TRANSITIONS.get(task.status, set())
        if payload.status != task.status and payload.status not in allowed:
            raise _problem(
                "INVALID_TASK_TRANSITION",
                f"Task cannot transition from {task.status} to {payload.status}.",
                409,
            )
        task.status = payload.status
        task.completed_at = (
            datetime.now(UTC) if payload.status == "COMPLETED" else None
        )
    if payload.priority is not None:
        task.priority = payload.priority
    if "assigned_to_subject" in payload.model_fields_set:
        task.assigned_to_subject = payload.assigned_to_subject
    if "due_at" in payload.model_fields_set:
        task.due_at = payload.due_at
    if "description" in payload.model_fields_set:
        task.description = payload.description
    task.version += 1
    db.add(
        _audit(
            user=user,
            action="admin_portal_task.updated",
            entity_type="portal_task",
            entity_id=task.id,
            details={
                "previous_status": previous_status,
                "status": task.status,
                "previous_assignee": previous_assignee,
                "assigned_to_subject": task.assigned_to_subject,
                "version": task.version,
            },
        )
    )
    if task.assigned_to_subject and task.assigned_to_subject != previous_assignee:
        db.add(
            PortalNotification(
                tenant_id=task.tenant_id,
                recipient_subject=task.assigned_to_subject,
                notification_type="TASK_ASSIGNED",
                title=task.title,
                body=task.description or "A MoneyBee task was assigned to you.",
                href=(
                    f"/applications/{task.application_id}"
                    if task.application_id
                    else "/tasks"
                ),
                metadata_payload={"task_id": str(task.id), "priority": task.priority},
            )
        )
    await db.commit()
    await db.refresh(task)
    return _public(
        task,
        (
            "id",
            "tenant_id",
            "application_id",
            "task_type",
            "title",
            "description",
            "status",
            "priority",
            "assigned_to_subject",
            "due_at",
            "completed_at",
            "version",
            "updated_at",
        ),
    )


@router.post("/notifications", status_code=201)
async def admin_create_notification(
    payload: AdminNotificationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    require_moneybee_admin(user.principal)
    membership_result = await db.execute(
        select(identity_models.OrganizationMembership).where(
            identity_models.OrganizationMembership.organization_id == payload.tenant_id,
            identity_models.OrganizationMembership.active.is_(True),
        )
    )
    active_subjects: set[str] = set()
    for membership in membership_result.scalars().all():
        user_row = await db.get(identity_models.User, membership.user_id)
        external_result = await db.execute(
            select(identity_models.ExternalIdentity).where(
                identity_models.ExternalIdentity.user_id == membership.user_id
            )
        )
        active_subjects.update(
            identity.subject for identity in external_result.scalars().all()
        )
        if user_row is not None and not bool(getattr(user_row, "active", True)):
            active_subjects.clear()
    if payload.recipient_subject not in active_subjects:
        raise _problem(
            "RECIPIENT_MEMBERSHIP_NOT_FOUND",
            "The recipient does not have an active membership in this organization.",
            422,
        )
    notification = PortalNotification(
        tenant_id=payload.tenant_id,
        recipient_subject=payload.recipient_subject,
        notification_type=payload.notification_type.upper(),
        title=payload.title.strip(),
        body=payload.body.strip(),
        href=payload.href,
        metadata_payload=payload.metadata_payload,
    )
    db.add(notification)
    await db.flush()
    db.add(
        _audit(
            user=user,
            action="admin_notification.created",
            entity_type="portal_notification",
            entity_id=notification.id,
            details={
                "tenant_id": str(payload.tenant_id),
                "recipient_subject": payload.recipient_subject,
                "notification_type": notification.notification_type,
            },
        )
    )
    await db.commit()
    await db.refresh(notification)
    return _public(
        notification,
        (
            "id",
            "tenant_id",
            "recipient_subject",
            "notification_type",
            "title",
            "body",
            "href",
            "created_at",
        ),
    )


@router.get("/search")
async def global_search(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    require_moneybee_admin(user.principal)
    pattern = f"%{q.strip()}%"
    lead_result = await db.execute(
        select(models.Lead)
        .where(
            or_(
                models.Lead.business_name.ilike(pattern),
                models.Lead.email.ilike(pattern),
                models.Lead.phone.ilike(pattern),
            )
        )
        .order_by(models.Lead.created_at.desc())
        .limit(limit)
    )
    organization_result = await db.execute(
        select(identity_models.Organization)
        .where(
            or_(
                identity_models.Organization.name.ilike(pattern),
                identity_models.Organization.organization_type.ilike(pattern),
            )
        )
        .order_by(identity_models.Organization.created_at.desc())
        .limit(limit)
    )
    users_result = await db.execute(
        select(identity_models.User)
        .where(
            or_(
                identity_models.User.email.ilike(pattern),
                identity_models.User.display_name.ilike(pattern),
            )
        )
        .order_by(identity_models.User.created_at.desc())
        .limit(limit)
    )
    return {
        "query": q.strip(),
        "leads": [
            _public(
                lead,
                ("id", "business_name", "email", "phone", "status", "created_at"),
            )
            for lead in lead_result.scalars().all()
        ],
        "organizations": [
            _public(
                organization,
                ("id", "name", "organization_type", "active", "created_at"),
            )
            for organization in organization_result.scalars().all()
        ],
        "users": [
            _public(
                user_row,
                ("id", "email", "display_name", "active", "created_at"),
            )
            for user_row in users_result.scalars().all()
        ],
    }


@router.get("/audit")
async def audit_log(
    action: str | None = None,
    entity_type: str | None = None,
    actor_subject: str | None = None,
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    require_moneybee_admin(user.principal)
    query = select(models.AuditEvent)
    if action:
        query = query.where(models.AuditEvent.action == action)
    if entity_type:
        query = query.where(models.AuditEvent.entity_type == entity_type)
    if actor_subject:
        query = query.where(models.AuditEvent.actor_subject == actor_subject)
    if before:
        query = query.where(models.AuditEvent.created_at < before)
    result = await db.execute(
        query.order_by(models.AuditEvent.created_at.desc()).limit(limit)
    )
    return [
        _public(
            event,
            (
                "id",
                "actor_subject",
                "action",
                "entity_type",
                "entity_id",
                "details",
                "created_at",
            ),
        )
        for event in result.scalars().all()
    ]


@router.get("/organizations")
async def list_organizations(
    organization_type: str | None = None,
    active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    require_moneybee_admin(user.principal)
    query = select(identity_models.Organization)
    if organization_type:
        query = query.where(
            identity_models.Organization.organization_type == organization_type.upper()
        )
    if active is not None:
        query = query.where(identity_models.Organization.active == active)
    result = await db.execute(
        query.order_by(identity_models.Organization.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        _public(
            organization,
            ("id", "name", "organization_type", "active", "created_at", "updated_at"),
        )
        for organization in result.scalars().all()
    ]


@router.get("/organizations/{organization_id}/members")
async def list_organization_members(
    organization_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    require_moneybee_admin(user.principal)
    organization = await db.get(identity_models.Organization, organization_id)
    if organization is None:
        raise _problem("ORGANIZATION_NOT_FOUND", "Organization was not found.", 404)
    result = await db.execute(
        select(identity_models.OrganizationMembership)
        .where(
            identity_models.OrganizationMembership.organization_id == organization_id
        )
        .order_by(identity_models.OrganizationMembership.created_at.asc())
    )
    output: list[dict[str, Any]] = []
    for membership in result.scalars().all():
        user_row = await db.get(identity_models.User, membership.user_id)
        identities = list(
            (
                await db.execute(
                    select(identity_models.ExternalIdentity).where(
                        identity_models.ExternalIdentity.user_id == membership.user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        output.append(
            {
                "membership": _public(
                    membership,
                    (
                        "organization_id",
                        "user_id",
                        "membership_type",
                        "active",
                        "created_at",
                    ),
                ),
                "user": _public(
                    user_row,
                    ("id", "email", "display_name", "active", "created_at"),
                ),
                "external_identities": [
                    _public(identity, ("issuer", "subject", "last_seen_at"))
                    for identity in identities
                ],
            }
        )
    return output
