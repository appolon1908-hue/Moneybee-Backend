from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import identity_models, models
from app.auth import Principal, current_principal
from app.db import get_db
from app.integration_models import OperationalException
from app.portal import models as portal_models
from app.portal.common import actor_type, completed_at, problem, require_any_permission
from app.portal.schemas import (
    AdminConversationUpdate,
    AdminOverview,
    AdminSearchResult,
    AdminTaskUpdate,
    AdminWorkspace,
    ConversationRead,
    MessageCreate,
    MessageRead,
    PageMeta,
    PortalNotificationCreate,
    PortalNotificationRead,
    PortalTaskCreate,
    PortalTaskRead,
)


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]
_TASK_TRANSITIONS = {
    "OPEN": {"IN_PROGRESS", "COMPLETED", "DISMISSED"},
    "IN_PROGRESS": {"OPEN", "COMPLETED", "DISMISSED"},
    "COMPLETED": {"OPEN"},
    "DISMISSED": {"OPEN"},
}


def _admin(user: Principal, *permissions: str) -> None:
    require_any_permission(user, *permissions)
    if "*" not in user.permissions and "MONEYBEE" not in user.membership_types:
        problem(
            "RESOURCE_ACCESS_DENIED",
            "An active MoneyBee organization membership is required.",
            403,
        )


async def _count(db: AsyncSession, model, *criteria) -> int:
    return int(await db.scalar(select(func.count(model.id)).where(*criteria)) or 0)


@router.get(
    "/admin/overview",
    response_model=AdminOverview,
    tags=["admin", "portal"],
)
async def admin_overview(db: Db, user: User):
    _admin(user, "lead.read", "application.read")
    status_rows = (
        await db.execute(
            select(models.Application.status, func.count(models.Application.id)).group_by(
                models.Application.status
            )
        )
    ).all()
    now = datetime.now(UTC)
    return AdminOverview(
        leads=await _count(db, models.Lead),
        applications=await _count(db, models.Application),
        applications_by_status={str(key): int(value) for key, value in status_rows},
        submissions_needing_review=await _count(
            db,
            models.LenderSubmission,
            models.LenderSubmission.status.in_(
                ["DRAFT", "QUEUED", "SUBMITTED", "UNDER_REVIEW", "ESCALATED"]
            ),
        ),
        open_tasks=await _count(
            db,
            portal_models.PortalTask,
            portal_models.PortalTask.status.in_(["OPEN", "IN_PROGRESS"]),
        ),
        overdue_tasks=await _count(
            db,
            portal_models.PortalTask,
            portal_models.PortalTask.status.in_(["OPEN", "IN_PROGRESS"]),
            portal_models.PortalTask.due_at.is_not(None),
            portal_models.PortalTask.due_at < now,
        ),
        unread_notifications=await _count(
            db,
            portal_models.PortalNotification,
            portal_models.PortalNotification.read_at.is_(None),
        ),
        open_conversations=await _count(
            db,
            portal_models.PortalConversation,
            portal_models.PortalConversation.status == "OPEN",
        ),
        open_complaints=await _count(
            db,
            models.Complaint,
            models.Complaint.status == "OPEN",
        ),
        open_operational_exceptions=await _count(
            db,
            OperationalException,
            OperationalException.status == "OPEN",
        ),
        pending_outbox=await _count(
            db,
            models.OutboxEvent,
            models.OutboxEvent.status.in_(
                [models.OutboxStatus.PENDING, models.OutboxStatus.RETRY]
            ),
        ),
        failed_integrations=await _count(
            db,
            models.IntegrationEvent,
            models.IntegrationEvent.status.in_(["FAILED", "DEAD"]),
        ),
        webhook_receipts_pending=await _count(
            db,
            models.WebhookReceipt,
            models.WebhookReceipt.status.in_(["RECEIVED", "RETRY"]),
        ),
    )


@router.get(
    "/admin/workspace",
    response_model=AdminWorkspace,
    tags=["admin", "portal"],
)
async def admin_workspace(db: Db, user: User):
    overview = await admin_overview(db, user)
    tasks = list(
        (
            await db.scalars(
                select(portal_models.PortalTask)
                .where(portal_models.PortalTask.status.in_(["OPEN", "IN_PROGRESS"]))
                .order_by(
                    portal_models.PortalTask.due_at.asc().nulls_last(),
                    portal_models.PortalTask.created_at.desc(),
                )
                .limit(100)
            )
        ).all()
    )
    exceptions = list(
        (
            await db.scalars(
                select(OperationalException)
                .where(OperationalException.status == "OPEN")
                .order_by(OperationalException.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return AdminWorkspace(
        principal={
            "global_scope": "*" in user.permissions
            or "MONEYBEE" in user.membership_types,
        },
        metrics={
            "lead_count": overview.leads,
            "application_count": overview.applications,
            "lender_submission_count": overview.submissions_needing_review,
            "open_task_count": overview.open_tasks,
            "overdue_task_count": overview.overdue_tasks,
            "unread_notification_count": overview.unread_notifications,
            "open_conversation_count": overview.open_conversations,
            "open_complaint_count": overview.open_complaints,
            "open_operational_exception_count": overview.open_operational_exceptions,
            "pending_outbox_count": overview.pending_outbox,
            "failed_integration_count": overview.failed_integrations,
            "webhook_receipts_pending": overview.webhook_receipts_pending,
            **overview.applications_by_status,
        },
        work_queue=[PortalTaskRead.model_validate(row) for row in tasks],
        operational_exceptions=[
            {
                "id": str(row.id),
                "code": row.code,
                "severity": row.severity,
                "status": row.status,
                "owner_subject": row.owner_subject,
                "sla_due_at": row.sla_due_at,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "correlation_id": row.correlation_id,
                "retry_action": row.retry_action,
                "resolution": row.resolution,
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
            }
            for row in exceptions
        ],
    )


@router.get("/admin/search", response_model=list[AdminSearchResult], tags=["admin", "portal"])
async def admin_search(
    db: Db,
    user: User,
    q: Annotated[str, Query(min_length=2, max_length=120)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    _admin(user, "lead.read", "application.read")
    needle = f"%{q.strip()}%"
    results: list[AdminSearchResult] = []
    leads = list(
        (
            await db.scalars(
                select(models.Lead)
                .where(
                    or_(
                        models.Lead.business_name.ilike(needle),
                        models.Lead.email.ilike(needle),
                        models.Lead.phone.ilike(needle),
                    )
                )
                .order_by(models.Lead.updated_at.desc())
                .limit(limit)
            )
        ).all()
    )
    results.extend(
        AdminSearchResult(
            resource_type="lead",
            resource_id=str(row.id),
            title=row.business_name,
            subtitle=f"{row.first_name} {row.last_name}",
            status=str(row.status),
            path=f"/leads/{row.id}",
            updated_at=row.updated_at,
        )
        for row in leads
    )
    try:
        resource_id = uuid.UUID(q.strip())
    except ValueError:
        resource_id = None
    if resource_id:
        application = await db.get(models.Application, resource_id)
        if application:
            results.insert(
                0,
                AdminSearchResult(
                    resource_type="application",
                    resource_id=str(application.id),
                    title=f"Application {str(application.id)[:8]}",
                    subtitle=f"Requested {application.requested_amount}",
                    status=str(application.status),
                    path=f"/applications/{application.id}",
                    updated_at=application.updated_at,
                ),
            )
    return results[:limit]


@router.get("/admin/tasks", tags=["admin", "portal"])
async def admin_tasks(
    db: Db,
    user: User,
    task_status: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    assignee_subject: Annotated[str | None, Query(max_length=255)] = None,
    application_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _admin(user, "lead.read", "application.read")
    filters = []
    if task_status:
        filters.append(portal_models.PortalTask.status == task_status)
    if assignee_subject:
        filters.append(portal_models.PortalTask.assignee_subject == assignee_subject)
    if application_id:
        filters.append(portal_models.PortalTask.application_id == application_id)
    total = await _count(db, portal_models.PortalTask, *filters)
    rows = list(
        (
            await db.scalars(
                select(portal_models.PortalTask)
                .where(*filters)
                .order_by(
                    portal_models.PortalTask.due_at.asc().nulls_last(),
                    portal_models.PortalTask.created_at.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )
    return {
        "items": [PortalTaskRead.model_validate(row) for row in rows],
        "meta": PageMeta(limit=limit, offset=offset, total=total),
    }


@router.post(
    "/admin/tasks",
    response_model=PortalTaskRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin", "portal"],
)
async def create_admin_task(payload: PortalTaskCreate, db: Db, user: User):
    _admin(user, "application.edit", "lead.read")
    if payload.application_id:
        application = await db.get(models.Application, payload.application_id)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        if (
            payload.organization_id
            and application.borrower_organization_id
            and payload.organization_id != application.borrower_organization_id
        ):
            problem(
                "TENANT_MISMATCH",
                "The task organization does not own the selected application.",
                422,
            )
    if payload.organization_id:
        organization = await db.get(identity_models.Organization, payload.organization_id)
        if organization is None or not organization.active:
            problem("ORGANIZATION_NOT_FOUND", "The task organization is not active.", 422)
    if payload.assignee_user_id:
        assigned_user = await db.get(identity_models.User, payload.assignee_user_id)
        if assigned_user is None or not assigned_user.active:
            problem("ASSIGNEE_NOT_FOUND", "The task assignee is not active.", 422)
    item = portal_models.PortalTask(**payload.model_dump())
    db.add(item)
    await db.flush()
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="PORTAL_TASK_CREATED",
            resource_type="portal_task",
            resource_id=str(item.id),
            details={
                "application_id": str(item.application_id) if item.application_id else None,
                "organization_id": str(item.organization_id) if item.organization_id else None,
                "assignee_subject": item.assignee_subject,
                "priority": item.priority,
            },
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.patch(
    "/admin/tasks/{task_id}",
    response_model=PortalTaskRead,
    tags=["admin", "portal"],
)
async def update_admin_task(
    task_id: uuid.UUID,
    payload: AdminTaskUpdate,
    db: Db,
    user: User,
):
    _admin(user, "application.edit", "lead.read")
    item = await db.scalar(
        select(portal_models.PortalTask)
        .where(portal_models.PortalTask.id == task_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Task not found")
    values = payload.model_dump(exclude_none=True)
    next_status = values.pop("status", None)
    if next_status and next_status != item.status:
        if next_status not in _TASK_TRANSITIONS.get(item.status, set()):
            problem(
                "INVALID_TASK_TRANSITION",
                f"Task cannot transition from {item.status} to {next_status}.",
                409,
            )
        item.status = next_status
        item.completed_at = completed_at(next_status)
    for name, value in values.items():
        setattr(item, name, value)
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="PORTAL_TASK_ADMIN_UPDATED",
            resource_type="portal_task",
            resource_id=str(item.id),
            details={"status": item.status, "fields": sorted(payload.model_fields_set)},
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.post(
    "/admin/notifications",
    response_model=PortalNotificationRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin", "communications"],
)
async def create_admin_notification(
    payload: PortalNotificationCreate,
    db: Db,
    user: User,
):
    _admin(user, "application.edit", "lead.read")
    if payload.application_id:
        application = await db.get(models.Application, payload.application_id)
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
    item = portal_models.PortalNotification(**payload.model_dump())
    db.add(item)
    await db.flush()
    db.add(
        models.OutboxEvent(
            event_type="PortalNotificationCreated",
            aggregate_type="portal_notification",
            aggregate_id=item.id,
            tenant_id=str(item.organization_id) if item.organization_id else None,
            payload={
                "notification_id": str(item.id),
                "subject": item.subject,
                "category": item.category,
                "application_id": str(item.application_id) if item.application_id else None,
            },
            idempotency_key=f"PortalNotificationCreated:{item.id}",
        )
    )
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="PORTAL_NOTIFICATION_CREATED",
            resource_type="portal_notification",
            resource_id=str(item.id),
            details={"subject": item.subject, "category": item.category},
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/admin/conversations",
    response_model=list[ConversationRead],
    tags=["admin", "messages"],
)
async def admin_conversations(
    db: Db,
    user: User,
    conversation_status: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    application_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    _admin(user, "lead.read", "application.read")
    statement = select(portal_models.PortalConversation)
    if conversation_status:
        statement = statement.where(portal_models.PortalConversation.status == conversation_status)
    if application_id:
        statement = statement.where(portal_models.PortalConversation.application_id == application_id)
    return list(
        (
            await db.scalars(
                statement.order_by(
                    portal_models.PortalConversation.last_message_at.desc().nulls_last(),
                    portal_models.PortalConversation.created_at.desc(),
                ).limit(limit)
            )
        ).all()
    )


@router.get(
    "/admin/conversations/{conversation_id}/messages",
    response_model=list[MessageRead],
    tags=["admin", "messages"],
)
async def admin_conversation_messages(conversation_id: uuid.UUID, db: Db, user: User):
    _admin(user, "lead.read", "application.read")
    conversation = await db.get(portal_models.PortalConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list(
        (
            await db.scalars(
                select(portal_models.PortalMessage)
                .where(portal_models.PortalMessage.conversation_id == conversation_id)
                .order_by(portal_models.PortalMessage.created_at)
                .limit(500)
            )
        ).all()
    )


@router.post(
    "/admin/conversations/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin", "messages"],
)
async def admin_send_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    db: Db,
    user: User,
):
    _admin(user, "application.edit", "lead.read")
    conversation = await db.scalar(
        select(portal_models.PortalConversation)
        .where(portal_models.PortalConversation.id == conversation_id)
        .with_for_update()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.status != "OPEN":
        problem("CONVERSATION_CLOSED", "The conversation is closed.", 409)
    if payload.attachment_document_id:
        document = await db.get(models.Document, payload.attachment_document_id)
        if document is None or document.application_id != conversation.application_id:
            problem("INVALID_ATTACHMENT", "The attachment is not part of this conversation.", 422)
    participant = await db.scalar(
        select(portal_models.PortalConversationParticipant).where(
            portal_models.PortalConversationParticipant.conversation_id == conversation.id,
            portal_models.PortalConversationParticipant.subject == user.subject,
        )
    )
    if participant is None:
        db.add(
            portal_models.PortalConversationParticipant(
                conversation_id=conversation.id,
                subject=user.subject,
                participant_type=actor_type(user),
                organization_id=user.active_organization_id,
                last_read_at=datetime.now(UTC),
            )
        )
    message = portal_models.PortalMessage(
        conversation_id=conversation.id,
        sender_subject=user.subject,
        sender_type=actor_type(user),
        body=payload.body,
        message_type="DOCUMENT" if payload.attachment_document_id else "TEXT",
        attachment_document_id=payload.attachment_document_id,
    )
    conversation.last_message_at = datetime.now(UTC)
    db.add(message)
    await db.flush()
    db.add(
        models.OutboxEvent(
            event_type="PortalMessageCreated",
            aggregate_type="portal_conversation",
            aggregate_id=conversation.id,
            tenant_id=str(conversation.organization_id) if conversation.organization_id else None,
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "application_id": str(conversation.application_id) if conversation.application_id else None,
            },
            idempotency_key=f"PortalMessageCreated:{message.id}",
        )
    )
    await db.commit()
    await db.refresh(message)
    return message


@router.patch(
    "/admin/conversations/{conversation_id}",
    response_model=ConversationRead,
    tags=["admin", "messages"],
)
async def update_admin_conversation(
    conversation_id: uuid.UUID,
    payload: AdminConversationUpdate,
    db: Db,
    user: User,
):
    _admin(user, "application.edit", "lead.read")
    item = await db.get(portal_models.PortalConversation, conversation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    item.status = payload.status
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="PORTAL_CONVERSATION_UPDATED",
            resource_type="portal_conversation",
            resource_id=str(item.id),
            details={"status": payload.status},
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/admin/audit-events", tags=["admin", "audit"])
async def admin_audit_events(
    db: Db,
    user: User,
    actor_id: Annotated[str | None, Query(max_length=255)] = None,
    action: Annotated[str | None, Query(max_length=120)] = None,
    resource_type: Annotated[str | None, Query(max_length=80)] = None,
    resource_id: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _admin(user, "capability.read", "lead.read")
    filters = []
    if actor_id:
        filters.append(models.AuditEvent.actor_id == actor_id)
    if action:
        filters.append(models.AuditEvent.action == action)
    if resource_type:
        filters.append(models.AuditEvent.resource_type == resource_type)
    if resource_id:
        filters.append(models.AuditEvent.resource_id == resource_id)
    total = await _count(db, models.AuditEvent, *filters)
    rows = list(
        (
            await db.scalars(
                select(models.AuditEvent)
                .where(*filters)
                .order_by(models.AuditEvent.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "actor_id": row.actor_id,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "request_id": row.request_id,
                "details": row.details,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "meta": PageMeta(limit=limit, offset=offset, total=total),
    }


@router.get("/admin/organizations", tags=["admin", "identity"])
async def admin_organizations(
    db: Db,
    user: User,
    organization_type: Annotated[str | None, Query(max_length=40)] = None,
    active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    _admin(user, "user.read", "capability.read")
    statement = select(identity_models.Organization)
    if organization_type:
        statement = statement.where(
            identity_models.Organization.organization_type == organization_type
        )
    if active is not None:
        statement = statement.where(identity_models.Organization.active.is_(active))
    rows = list(
        (
            await db.scalars(
                statement.order_by(identity_models.Organization.name).limit(limit)
            )
        ).all()
    )
    result = []
    for row in rows:
        member_count = await _count(
            db,
            identity_models.OrganizationMembership,
            identity_models.OrganizationMembership.organization_id == row.id,
            identity_models.OrganizationMembership.active.is_(True),
        )
        result.append(
            {
                "id": str(row.id),
                "name": row.name,
                "organization_type": row.organization_type,
                "active": row.active,
                "member_count": member_count,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    return result


@router.get("/admin/organizations/{organization_id}/members", tags=["admin", "identity"])
async def admin_organization_members(
    organization_id: uuid.UUID,
    db: Db,
    user: User,
):
    _admin(user, "user.read", "capability.read")
    organization = await db.get(identity_models.Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    memberships = (
        await db.execute(
            select(identity_models.OrganizationMembership, identity_models.User)
            .join(
                identity_models.User,
                identity_models.User.id == identity_models.OrganizationMembership.user_id,
            )
            .where(identity_models.OrganizationMembership.organization_id == organization_id)
            .order_by(identity_models.User.display_name, identity_models.User.email)
        )
    ).all()
    result = []
    for membership, member in memberships:
        roles = list(
            await db.scalars(
                select(identity_models.Role.code)
                .join(
                    identity_models.UserRoleBinding,
                    identity_models.UserRoleBinding.role_id == identity_models.Role.id,
                )
                .where(
                    identity_models.UserRoleBinding.user_id == member.id,
                    identity_models.UserRoleBinding.organization_id == organization_id,
                    identity_models.UserRoleBinding.active.is_(True),
                    identity_models.Role.active.is_(True),
                )
                .order_by(identity_models.Role.code)
            )
        )
        result.append(
            {
                "membership_id": str(membership.id),
                "user_id": str(member.id),
                "email": member.email,
                "display_name": member.display_name,
                "membership_type": membership.membership_type,
                "membership_active": membership.active,
                "user_active": member.active,
                "roles": roles,
                "created_at": membership.created_at,
            }
        )
    return result
