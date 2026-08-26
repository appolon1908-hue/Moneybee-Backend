import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.auth import Principal, User, get_current_user
from app.db import get_db
from app.portal_models import (
    PortalConversation,
    PortalMessage,
    PortalNotification,
    PortalTask,
)
from app.portal_schemas import (
    AuthContextRead,
    NavigationItem,
    PortalConversationCreate,
    PortalConversationRead,
    PortalMessageCreate,
    PortalMessageRead,
    PortalNotificationRead,
    PortalTaskCreate,
    PortalTaskRead,
    PortalTaskUpdate,
)
from app.portal_security import (
    active_tenant,
    ensure_conversation_access,
    ensure_subject_or_admin,
    ensure_tenant_access,
    is_moneybee_admin,
)

router = APIRouter(tags=["portal"])


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _navigation(principal: Principal) -> list[NavigationItem]:
    items = [
        NavigationItem(
            key="profile",
            label="Profile",
            href="/profile",
            portal="shared",
        ),
        NavigationItem(
            key="messages",
            label="Messages",
            href="/messages",
            portal="shared",
        ),
        NavigationItem(
            key="tasks",
            label="Tasks",
            href="/tasks",
            portal="shared",
        ),
        NavigationItem(
            key="notifications",
            label="Notifications",
            href="/notifications",
            portal="shared",
        ),
    ]
    if principal.borrower_id is not None and "BORROWER" in principal.membership_types:
        items.extend(
            [
                NavigationItem(
                    key="borrower-dashboard",
                    label="Dashboard",
                    href="/dashboard",
                    portal="borrower",
                ),
                NavigationItem(
                    key="borrower-applications",
                    label="Applications",
                    href="/applications",
                    portal="borrower",
                ),
                NavigationItem(
                    key="borrower-documents",
                    label="Documents",
                    href="/documents",
                    portal="borrower",
                ),
                NavigationItem(
                    key="borrower-offers",
                    label="Offers",
                    href="/offers",
                    portal="borrower",
                ),
            ]
        )
    if principal.lender_id is not None and "LENDER" in principal.membership_types:
        items.extend(
            [
                NavigationItem(
                    key="lender-dashboard",
                    label="Lender dashboard",
                    href="/dashboard",
                    portal="lender",
                ),
                NavigationItem(
                    key="lender-submissions",
                    label="Submissions",
                    href="/submissions",
                    portal="lender",
                ),
                NavigationItem(
                    key="lender-programs",
                    label="Programs",
                    href="/programs",
                    portal="lender",
                ),
                NavigationItem(
                    key="lender-bank-analysis",
                    label="Bank analysis",
                    href="/bank-analysis",
                    portal="lender",
                ),
                NavigationItem(
                    key="lender-portfolio",
                    label="Portfolio",
                    href="/portfolio",
                    portal="lender",
                ),
            ]
        )
    if is_moneybee_admin(principal):
        items.extend(
            [
                NavigationItem(
                    key="admin-operations",
                    label="Operations",
                    href="/operations",
                    portal="admin",
                ),
                NavigationItem(
                    key="admin-work-queue",
                    label="Work queue",
                    href="/work-queue",
                    portal="admin",
                ),
                NavigationItem(
                    key="admin-organizations",
                    label="Organizations",
                    href="/organizations",
                    portal="admin",
                ),
                NavigationItem(
                    key="admin-search",
                    label="Search",
                    href="/search",
                    portal="admin",
                ),
                NavigationItem(
                    key="admin-webhooks",
                    label="Webhook operations",
                    href="/webhooks",
                    portal="admin",
                ),
            ]
        )
    seen: set[tuple[str, str]] = set()
    unique: list[NavigationItem] = []
    for item in items:
        key = (item.portal, item.key)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _audit(
    *,
    principal: Principal,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    details: dict,
) -> models.AuditEvent:
    return models.AuditEvent(
        actor_subject=principal.subject,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details={
            **details,
            "organization_id": str(active_tenant(principal)),
            "user_id": str(principal.user_id),
        },
    )


@router.get("/auth/context", response_model=AuthContextRead)
async def auth_context(user: User = Depends(get_current_user)) -> AuthContextRead:
    principal = user.principal
    return AuthContextRead(
        user_id=principal.user_id,
        subject=principal.subject,
        active_organization_id=active_tenant(principal),
        organization_ids=principal.organization_ids,
        roles=sorted(principal.roles),
        permissions=sorted(principal.permissions),
        membership_types=sorted(principal.membership_types),
        borrower_id=principal.borrower_id,
        lender_id=principal.lender_id,
        navigation=_navigation(principal),
    )


@router.get("/portal/navigation", response_model=list[NavigationItem])
async def portal_navigation(user: User = Depends(get_current_user)) -> list[NavigationItem]:
    return _navigation(user.principal)


@router.get("/portal/tasks", response_model=list[PortalTaskRead])
async def list_tasks(
    status: str | None = None,
    application_id: uuid.UUID | None = None,
    assigned_to_me: bool = True,
    limit: int = Query(default=100, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortalTask]:
    principal = user.principal
    query = select(PortalTask).where(PortalTask.tenant_id == active_tenant(principal))
    if status:
        query = query.where(PortalTask.status == status.upper())
    if application_id:
        query = query.where(PortalTask.application_id == application_id)
    if assigned_to_me and not is_moneybee_admin(principal):
        query = query.where(
            or_(
                PortalTask.assigned_to_subject == principal.subject,
                PortalTask.assigned_to_subject.is_(None),
            )
        )
    query = query.order_by(PortalTask.due_at.asc(), PortalTask.created_at.desc())
    result = await db.execute(query.limit(limit).offset(offset))
    return list(result.scalars().all())


@router.post("/portal/tasks", response_model=PortalTaskRead, status_code=201)
async def create_task(
    payload: PortalTaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalTask:
    principal = user.principal
    tenant_id = active_tenant(principal)
    assignee = payload.assigned_to_subject
    if not is_moneybee_admin(principal):
        assignee = principal.subject
    task = PortalTask(
        tenant_id=tenant_id,
        application_id=payload.application_id,
        task_type=payload.task_type.upper(),
        title=payload.title.strip(),
        description=payload.description,
        priority=payload.priority,
        assigned_to_subject=assignee,
        created_by_subject=principal.subject,
        due_at=payload.due_at,
        metadata_payload=payload.metadata_payload,
    )
    db.add(task)
    await db.flush()
    db.add(
        _audit(
            principal=principal,
            action="portal_task.created",
            entity_type="portal_task",
            entity_id=task.id,
            details={"status": task.status, "priority": task.priority},
        )
    )
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/portal/tasks/{task_id}", response_model=PortalTaskRead)
async def update_task(
    task_id: uuid.UUID,
    payload: PortalTaskUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalTask:
    principal = user.principal
    task = await db.get(PortalTask, task_id)
    if task is None:
        raise _problem("PORTAL_TASK_NOT_FOUND", "Portal task was not found.", 404)
    ensure_tenant_access(principal, task.tenant_id)
    ensure_subject_or_admin(principal, task.assigned_to_subject)
    if task.version != payload.expected_version:
        raise _problem(
            "RESOURCE_VERSION_CONFLICT",
            "The portal task was modified by another request.",
            409,
        )
    previous_status = task.status
    if payload.status is not None:
        task.status = payload.status
        task.completed_at = (
            datetime.now(UTC) if payload.status == "COMPLETED" else None
        )
    if payload.priority is not None:
        task.priority = payload.priority
    if "assigned_to_subject" in payload.model_fields_set:
        if not is_moneybee_admin(principal):
            raise _problem(
                "TASK_ASSIGNMENT_FORBIDDEN",
                "Only a MoneyBee administrator may reassign portal tasks.",
                403,
            )
        task.assigned_to_subject = payload.assigned_to_subject
    if "due_at" in payload.model_fields_set:
        task.due_at = payload.due_at
    if "description" in payload.model_fields_set:
        task.description = payload.description
    task.version += 1
    db.add(
        _audit(
            principal=principal,
            action="portal_task.updated",
            entity_type="portal_task",
            entity_id=task.id,
            details={
                "previous_status": previous_status,
                "status": task.status,
                "version": task.version,
            },
        )
    )
    await db.commit()
    await db.refresh(task)
    return task


@router.get("/portal/notifications", response_model=list[PortalNotificationRead])
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=100, ge=1, le=250),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortalNotification]:
    principal = user.principal
    query = select(PortalNotification).where(
        PortalNotification.tenant_id == active_tenant(principal),
        PortalNotification.recipient_subject == principal.subject,
    )
    if unread_only:
        query = query.where(PortalNotification.read_at.is_(None))
    result = await db.execute(
        query.order_by(PortalNotification.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.post(
    "/portal/notifications/{notification_id}/read",
    response_model=PortalNotificationRead,
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalNotification:
    principal = user.principal
    notification = await db.get(PortalNotification, notification_id)
    if notification is None:
        raise _problem(
            "PORTAL_NOTIFICATION_NOT_FOUND",
            "Portal notification was not found.",
            404,
        )
    ensure_tenant_access(principal, notification.tenant_id)
    if notification.recipient_subject != principal.subject:
        raise _problem(
            "RESOURCE_ACCESS_DENIED",
            "The authenticated user does not own this notification.",
            403,
        )
    notification.read_at = notification.read_at or datetime.now(UTC)
    await db.commit()
    await db.refresh(notification)
    return notification


@router.get("/portal/conversations", response_model=list[PortalConversationRead])
async def list_conversations(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=250),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortalConversation]:
    principal = user.principal
    query = select(PortalConversation).where(
        PortalConversation.tenant_id == active_tenant(principal)
    )
    if status:
        query = query.where(PortalConversation.status == status.upper())
    result = await db.execute(
        query.order_by(PortalConversation.last_message_at.desc()).limit(limit)
    )
    conversations = list(result.scalars().all())
    if is_moneybee_admin(principal):
        return conversations
    return [
        conversation
        for conversation in conversations
        if principal.subject in conversation.participant_subjects
    ]


@router.post(
    "/portal/conversations",
    response_model=PortalConversationRead,
    status_code=201,
)
async def create_conversation(
    payload: PortalConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalConversation:
    principal = user.principal
    participants = list(
        dict.fromkeys([principal.subject, *payload.participant_subjects])
    )
    conversation = PortalConversation(
        tenant_id=active_tenant(principal),
        application_id=payload.application_id,
        topic=payload.topic.strip(),
        created_by_subject=principal.subject,
        participant_subjects=participants,
        metadata_payload=payload.metadata_payload,
    )
    db.add(conversation)
    await db.flush()
    if payload.opening_message:
        db.add(
            PortalMessage(
                conversation_id=conversation.id,
                sender_subject=principal.subject,
                body=payload.opening_message.strip(),
            )
        )
    db.add(
        _audit(
            principal=principal,
            action="portal_conversation.created",
            entity_type="portal_conversation",
            entity_id=conversation.id,
            details={"application_id": str(payload.application_id or "")},
        )
    )
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def _conversation(
    *,
    conversation_id: uuid.UUID,
    principal: Principal,
    db: AsyncSession,
) -> PortalConversation:
    conversation = await db.get(PortalConversation, conversation_id)
    if conversation is None:
        raise _problem(
            "PORTAL_CONVERSATION_NOT_FOUND",
            "Portal conversation was not found.",
            404,
        )
    ensure_conversation_access(
        principal,
        tenant_id=conversation.tenant_id,
        participant_subjects=conversation.participant_subjects,
    )
    return conversation


@router.get(
    "/portal/conversations/{conversation_id}/messages",
    response_model=list[PortalMessageRead],
)
async def list_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortalMessage]:
    await _conversation(
        conversation_id=conversation_id,
        principal=user.principal,
        db=db,
    )
    result = await db.execute(
        select(PortalMessage)
        .where(PortalMessage.conversation_id == conversation_id)
        .order_by(PortalMessage.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.post(
    "/portal/conversations/{conversation_id}/messages",
    response_model=PortalMessageRead,
    status_code=201,
)
async def create_message(
    conversation_id: uuid.UUID,
    payload: PortalMessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalMessage:
    principal = user.principal
    conversation = await _conversation(
        conversation_id=conversation_id,
        principal=principal,
        db=db,
    )
    if conversation.status == "CLOSED":
        raise _problem(
            "PORTAL_CONVERSATION_CLOSED",
            "Messages cannot be added to a closed conversation.",
            409,
        )
    message = PortalMessage(
        conversation_id=conversation.id,
        sender_subject=principal.subject,
        body=payload.body.strip(),
        attachments=payload.attachments,
        metadata_payload=payload.metadata_payload,
    )
    conversation.last_message_at = datetime.now(UTC)
    db.add(message)
    await db.flush()
    db.add(
        _audit(
            principal=principal,
            action="portal_message.created",
            entity_type="portal_message",
            entity_id=message.id,
            details={"conversation_id": str(conversation.id)},
        )
    )
    await db.commit()
    await db.refresh(message)
    return message
