from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, services
from app.auth import Principal, current_principal
from app.db import get_db
from app.integrations.base import ProviderError
from app.integrations.storage import S3ObjectStorageAdapter
from app.portal import models as portal_models
from app.portal.common import actor_type, completed_at, problem
from app.portal.schemas import (
    BorrowerOverview,
    ConversationCreate,
    ConversationRead,
    DocumentDownload,
    DocumentRead,
    MessageCreate,
    MessageRead,
    PortalNotificationRead,
    PortalTaskRead,
    PortalTaskUpdate,
    UploadSessionComplete,
    UploadSessionCreate,
    UploadSessionRead,
)


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]

_ALLOWED_DOCUMENT_TYPES = {
    "BANK_STATEMENT",
    "BUSINESS_LICENSE",
    "DRIVER_LICENSE",
    "EIN_LETTER",
    "TAX_RETURN",
    "VOIDED_CHECK",
    "OTHER",
}
_ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
_TASK_TRANSITIONS = {
    "OPEN": {"IN_PROGRESS", "COMPLETED", "DISMISSED"},
    "IN_PROGRESS": {"OPEN", "COMPLETED", "DISMISSED"},
    "COMPLETED": set(),
    "DISMISSED": set(),
}


def _borrower_filter(user: Principal):
    if "*" in user.permissions:
        return None
    if user.borrower_id is None:
        problem(
            "RESOURCE_ACCESS_DENIED",
            "An active borrower organization membership is required.",
            403,
        )
    return or_(
        models.Application.borrower_organization_id == user.borrower_id,
        (
            models.Application.borrower_organization_id.is_(None)
            & (models.Application.borrower_subject == user.subject)
        ),
    )


def _application_payload(item: models.Application) -> dict:
    return {
        "id": str(item.id),
        "lead_id": str(item.lead_id),
        "requested_amount": str(item.requested_amount),
        "monthly_revenue": str(item.monthly_revenue),
        "time_in_business_months": item.time_in_business_months,
        "industry": item.industry,
        "state": item.state,
        "status": item.status,
        "completion_percentage": item.completion_percentage,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def _borrower_applications(db: AsyncSession, user: Principal) -> list[models.Application]:
    statement = select(models.Application)
    scope = _borrower_filter(user)
    if scope is not None:
        statement = statement.where(scope)
    return list(
        (
            await db.scalars(
                statement.order_by(models.Application.updated_at.desc()).limit(100)
            )
        ).all()
    )


async def _authorize_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    user: Principal,
) -> portal_models.PortalTask:
    task = await db.get(portal_models.PortalTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if "*" in user.permissions:
        return task
    allowed = task.assignee_subject == user.subject or task.assignee_user_id == user.user_id
    if user.borrower_id and task.organization_id == user.borrower_id:
        allowed = True
    if not allowed:
        problem("RESOURCE_ACCESS_DENIED", "The task is outside the active borrower organization.", 403)
    if task.application_id:
        await services.get_authorized_application(db, task.application_id, user)
    return task


async def _conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user: Principal,
) -> portal_models.PortalConversation:
    item = await db.get(portal_models.PortalConversation, conversation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if "*" not in user.permissions:
        participant = await db.scalar(
            select(portal_models.PortalConversationParticipant).where(
                portal_models.PortalConversationParticipant.conversation_id == item.id,
                portal_models.PortalConversationParticipant.subject == user.subject,
            )
        )
        if participant is None:
            problem("RESOURCE_ACCESS_DENIED", "The conversation is not available to this user.", 403)
    if item.application_id:
        await services.get_authorized_application(db, item.application_id, user)
    return item


def _safe_name(value: str) -> str:
    name = PurePath(value.replace("\\", "/")).name
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not clean:
        problem("INVALID_FILE_NAME", "The file name is invalid.", 422)
    return clean[:180]


@router.get(
    "/borrower/overview",
    response_model=BorrowerOverview,
    tags=["borrower", "portal"],
)
async def borrower_overview(db: Db, user: User):
    applications = await _borrower_applications(db, user)
    active = next(
        (
            item
            for item in applications
            if item.status
            not in {
                models.ApplicationStatus.CLOSED,
                models.ApplicationStatus.WITHDRAWN,
                models.ApplicationStatus.DECLINED,
                models.ApplicationStatus.EXPIRED,
                models.ApplicationStatus.CANCELLED,
            }
        ),
        applications[0] if applications else None,
    )
    application_ids = [item.id for item in applications]
    task_filters = [portal_models.PortalTask.assignee_subject == user.subject]
    notification_filters = [portal_models.PortalNotification.subject == user.subject]
    if user.borrower_id:
        task_filters.append(portal_models.PortalTask.organization_id == user.borrower_id)
        notification_filters.append(
            portal_models.PortalNotification.organization_id == user.borrower_id
        )
    task_statement = select(func.count(portal_models.PortalTask.id)).where(
        portal_models.PortalTask.status.in_(["OPEN", "IN_PROGRESS"]),
        or_(*task_filters),
    )
    notification_statement = select(func.count(portal_models.PortalNotification.id)).where(
        portal_models.PortalNotification.read_at.is_(None),
        or_(*notification_filters),
    )
    open_conditions = 0
    available_offers = 0
    recent_activity: list[dict] = []
    if application_ids:
        open_conditions = (
            await db.scalar(
                select(func.count(models.UnderwritingCondition.id)).where(
                    models.UnderwritingCondition.application_id.in_(application_ids),
                    models.UnderwritingCondition.status.in_(
                        ["BORROWER_ACTION_REQUIRED", "REJECTED"]
                    ),
                )
            )
            or 0
        )
        available_offers = (
            await db.scalar(
                select(func.count(models.Offer.id)).where(
                    models.Offer.application_id.in_(application_ids),
                    models.Offer.status == "AVAILABLE",
                    or_(models.Offer.expires_at.is_(None), models.Offer.expires_at > datetime.now(UTC)),
                )
            )
            or 0
        )
        history = list(
            (
                await db.scalars(
                    select(models.ApplicationStatusHistory)
                    .where(models.ApplicationStatusHistory.application_id.in_(application_ids))
                    .order_by(models.ApplicationStatusHistory.created_at.desc())
                    .limit(20)
                )
            ).all()
        )
        recent_activity = [
            {
                "id": str(row.id),
                "application_id": str(row.application_id),
                "type": "APPLICATION_STATUS",
                "label": str(row.to_status).replace("_", " ").title(),
                "detail": row.reason,
                "occurred_at": row.created_at,
            }
            for row in history
        ]
    return BorrowerOverview(
        active_application=_application_payload(active) if active else None,
        applications=[_application_payload(item) for item in applications],
        requirements=(await services.application_requirements(db, active) if active else None),
        open_tasks=(await db.scalar(task_statement) or 0),
        unread_notifications=(await db.scalar(notification_statement) or 0),
        open_conditions=open_conditions,
        available_offers=available_offers,
        recent_activity=recent_activity,
    )


@router.get(
    "/borrower/tasks",
    response_model=list[PortalTaskRead],
    tags=["borrower", "portal"],
)
async def borrower_tasks(
    db: Db,
    user: User,
    task_status: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    filters = [portal_models.PortalTask.assignee_subject == user.subject]
    if user.borrower_id:
        filters.append(portal_models.PortalTask.organization_id == user.borrower_id)
    if "*" in user.permissions and user.active_organization_id is None:
        statement = select(portal_models.PortalTask)
    else:
        statement = select(portal_models.PortalTask).where(or_(*filters))
    if task_status:
        statement = statement.where(portal_models.PortalTask.status == task_status)
    return list(
        (
            await db.scalars(
                statement.order_by(
                    portal_models.PortalTask.due_at.asc().nulls_last(),
                    portal_models.PortalTask.created_at.desc(),
                ).limit(limit)
            )
        ).all()
    )


@router.patch(
    "/borrower/tasks/{task_id}",
    response_model=PortalTaskRead,
    tags=["borrower", "portal"],
)
async def update_borrower_task(
    task_id: uuid.UUID,
    payload: PortalTaskUpdate,
    db: Db,
    user: User,
):
    item = await _authorize_task(db, task_id, user)
    if payload.status == item.status:
        return item
    if payload.status not in _TASK_TRANSITIONS.get(item.status, set()):
        problem(
            "INVALID_TASK_TRANSITION",
            f"Task cannot transition from {item.status} to {payload.status}.",
            409,
        )
    item.status = payload.status
    item.completed_at = completed_at(payload.status)
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="PORTAL_TASK_UPDATED",
            resource_type="portal_task",
            resource_id=str(item.id),
            details={"status": payload.status},
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/borrower/notifications",
    response_model=list[PortalNotificationRead],
    tags=["borrower", "portal"],
)
async def borrower_notifications(
    db: Db,
    user: User,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    filters = [portal_models.PortalNotification.subject == user.subject]
    if user.borrower_id:
        filters.append(portal_models.PortalNotification.organization_id == user.borrower_id)
    statement = select(portal_models.PortalNotification)
    if "*" not in user.permissions or user.active_organization_id is not None:
        statement = statement.where(or_(*filters))
    if unread_only:
        statement = statement.where(portal_models.PortalNotification.read_at.is_(None))
    return list(
        (
            await db.scalars(
                statement.order_by(portal_models.PortalNotification.created_at.desc()).limit(limit)
            )
        ).all()
    )


@router.post(
    "/borrower/notifications/{notification_id}/read",
    response_model=PortalNotificationRead,
    tags=["borrower", "portal"],
)
async def read_borrower_notification(
    notification_id: uuid.UUID,
    db: Db,
    user: User,
):
    item = await db.get(portal_models.PortalNotification, notification_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    allowed = item.subject == user.subject
    if user.borrower_id and item.organization_id == user.borrower_id:
        allowed = True
    if "*" not in user.permissions and not allowed:
        problem("RESOURCE_ACCESS_DENIED", "The notification is not available to this user.", 403)
    if item.read_at is None:
        item.read_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(item)
    return item


@router.get(
    "/borrower/conversations",
    response_model=list[ConversationRead],
    tags=["borrower", "messages"],
)
async def borrower_conversations(db: Db, user: User):
    statement = (
        select(portal_models.PortalConversation)
        .join(
            portal_models.PortalConversationParticipant,
            portal_models.PortalConversationParticipant.conversation_id
            == portal_models.PortalConversation.id,
        )
        .where(portal_models.PortalConversationParticipant.subject == user.subject)
        .order_by(
            portal_models.PortalConversation.last_message_at.desc().nulls_last(),
            portal_models.PortalConversation.created_at.desc(),
        )
    )
    if "*" in user.permissions and user.active_organization_id is None:
        statement = select(portal_models.PortalConversation).order_by(
            portal_models.PortalConversation.last_message_at.desc().nulls_last()
        )
    return list((await db.scalars(statement.limit(100))).unique().all())


@router.post(
    "/borrower/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    tags=["borrower", "messages"],
)
async def create_borrower_conversation(
    payload: ConversationCreate,
    db: Db,
    user: User,
):
    if payload.application_id:
        await services.get_authorized_application(db, payload.application_id, user)
    organization_id = user.borrower_id or user.active_organization_id
    now = datetime.now(UTC)
    item = portal_models.PortalConversation(
        application_id=payload.application_id,
        organization_id=organization_id,
        topic=payload.topic,
        created_by_subject=user.subject,
        last_message_at=now,
    )
    db.add(item)
    await db.flush()
    db.add(
        portal_models.PortalConversationParticipant(
            conversation_id=item.id,
            subject=user.subject,
            participant_type=actor_type(user),
            organization_id=organization_id,
            last_read_at=now,
        )
    )
    db.add(
        portal_models.PortalMessage(
            conversation_id=item.id,
            sender_subject=user.subject,
            sender_type=actor_type(user),
            body=payload.body,
        )
    )
    db.add(
        models.OutboxEvent(
            event_type="PortalConversationOpened",
            aggregate_type="portal_conversation",
            aggregate_id=item.id,
            tenant_id=str(organization_id) if organization_id else None,
            payload={
                "conversation_id": str(item.id),
                "application_id": str(payload.application_id) if payload.application_id else None,
                "topic": payload.topic,
            },
            idempotency_key=f"PortalConversationOpened:{item.id}",
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/borrower/conversations/{conversation_id}/messages",
    response_model=list[MessageRead],
    tags=["borrower", "messages"],
)
async def borrower_messages(
    conversation_id: uuid.UUID,
    db: Db,
    user: User,
):
    await _conversation(db, conversation_id, user)
    participant = await db.scalar(
        select(portal_models.PortalConversationParticipant).where(
            portal_models.PortalConversationParticipant.conversation_id == conversation_id,
            portal_models.PortalConversationParticipant.subject == user.subject,
        )
    )
    if participant:
        participant.last_read_at = datetime.now(UTC)
        await db.commit()
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
    "/borrower/conversations/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    tags=["borrower", "messages"],
)
async def send_borrower_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    db: Db,
    user: User,
):
    conversation = await _conversation(db, conversation_id, user)
    if conversation.status != "OPEN":
        problem("CONVERSATION_CLOSED", "The conversation is closed.", 409)
    if payload.attachment_document_id:
        document = await db.get(models.Document, payload.attachment_document_id)
        if document is None or document.application_id != conversation.application_id:
            problem("INVALID_ATTACHMENT", "The attachment is not part of this conversation's application.", 422)
        await services.get_authorized_application(db, document.application_id, user)
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


@router.get(
    "/borrower/applications/{application_id}/documents",
    response_model=list[DocumentRead],
    tags=["borrower", "documents"],
)
async def borrower_documents(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.Document)
                .where(models.Document.application_id == application_id)
                .order_by(models.Document.created_at.desc())
            )
        ).all()
    )


@router.post(
    "/borrower/applications/{application_id}/documents/upload-sessions",
    response_model=UploadSessionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["borrower", "documents"],
)
async def create_document_upload_session(
    application_id: uuid.UUID,
    payload: UploadSessionCreate,
    db: Db,
    user: User,
):
    await services.require_capability(db, "documents.secure_upload")
    await services.get_authorized_application(db, application_id, user, write=True)
    document_type = payload.document_type.upper()
    if document_type not in _ALLOWED_DOCUMENT_TYPES:
        problem("DOCUMENT_TYPE_NOT_ALLOWED", "The document type is not allowed.", 422)
    if payload.mime_type.lower() not in _ALLOWED_MIME_TYPES:
        problem("DOCUMENT_MIME_NOT_ALLOWED", "Only PDF, JPEG, and PNG documents are accepted.", 422)
    filename = _safe_name(payload.original_file_name)
    session_id = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    storage_key = f"applications/{application_id}/quarantine/{session_id}/{filename}"
    adapter = S3ObjectStorageAdapter()
    try:
        upload_url = await adapter.presigned_upload(
            object_key=storage_key,
            content_type=payload.mime_type.lower(),
            expires_seconds=600,
        )
    except ProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DOCUMENT_STORAGE_UNAVAILABLE",
                "message": "Secure document storage is not available.",
            },
        ) from exc
    item = portal_models.DocumentUploadSession(
        id=session_id,
        application_id=application_id,
        created_by_subject=user.subject,
        document_type=document_type,
        original_file_name=filename,
        mime_type=payload.mime_type.lower(),
        size_bytes=payload.size_bytes,
        expected_sha256=payload.sha256.lower() if payload.sha256 else None,
        storage_key=storage_key,
        expires_at=expires_at,
        metadata_payload={"quarantine": True},
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return UploadSessionRead(
        **{
            "id": item.id,
            "application_id": item.application_id,
            "document_type": item.document_type,
            "original_file_name": item.original_file_name,
            "mime_type": item.mime_type,
            "size_bytes": item.size_bytes,
            "expected_sha256": item.expected_sha256,
            "status": item.status,
            "expires_at": item.expires_at,
            "created_at": item.created_at,
            "upload_url": upload_url,
            "upload_headers": {
                "Content-Type": item.mime_type,
                "x-amz-server-side-encryption": "AES256",
            },
        }
    )


@router.post(
    "/borrower/document-upload-sessions/{session_id}/complete",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["borrower", "documents"],
)
async def complete_document_upload_session(
    session_id: uuid.UUID,
    payload: UploadSessionComplete,
    db: Db,
    user: User,
):
    await services.require_capability(db, "documents.secure_upload")
    item = await db.scalar(
        select(portal_models.DocumentUploadSession)
        .where(portal_models.DocumentUploadSession.id == session_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Upload session not found")
    await services.get_authorized_application(db, item.application_id, user, write=True)
    if "*" not in user.permissions and item.created_by_subject != user.subject:
        problem("RESOURCE_ACCESS_DENIED", "The upload session belongs to another user.", 403)
    if item.status != "CREATED":
        problem("UPLOAD_SESSION_NOT_ACTIVE", "The upload session is not active.", 409)
    expires_at = item.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        item.status = "EXPIRED"
        await db.commit()
        problem("UPLOAD_SESSION_EXPIRED", "The upload session has expired.", 409)
    if payload.size_bytes != item.size_bytes:
        problem("DOCUMENT_SIZE_MISMATCH", "The uploaded document size does not match the request.", 409)
    supplied_hash = payload.sha256.lower()
    if item.expected_sha256 and supplied_hash != item.expected_sha256:
        problem("DOCUMENT_HASH_MISMATCH", "The uploaded document checksum does not match.", 409)
    adapter = S3ObjectStorageAdapter()
    try:
        metadata = await adapter.head_private(object_key=item.storage_key)
    except ProviderError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DOCUMENT_UPLOAD_NOT_FOUND", "message": "The uploaded object could not be verified."},
        ) from exc
    if int(metadata.get("ContentLength") or -1) != item.size_bytes:
        problem("DOCUMENT_SIZE_MISMATCH", "The stored document size does not match.", 409)
    document = models.Document(
        application_id=item.application_id,
        document_type=item.document_type,
        original_file_name=item.original_file_name,
        mime_type=item.mime_type,
        size_bytes=item.size_bytes,
        storage_key=item.storage_key,
        sha256=supplied_hash,
        status="QUARANTINED",
        uploaded_by=user.subject,
    )
    item.status = "UPLOADED"
    item.completed_at = datetime.now(UTC)
    item.provider_reference = str(metadata.get("VersionId") or metadata.get("ETag") or "")[:255] or None
    db.add(document)
    await db.flush()
    db.add(
        models.OutboxEvent(
            event_type="DocumentUploaded",
            aggregate_type="document",
            aggregate_id=document.id,
            tenant_id=str(user.active_organization_id) if user.active_organization_id else None,
            payload={
                "document_id": str(document.id),
                "application_id": str(document.application_id),
                "storage_key": document.storage_key,
                "sha256": document.sha256,
                "status": document.status,
            },
            idempotency_key=f"DocumentUploaded:{document.id}:{document.sha256}",
            destination="document-scanner",
        )
    )
    await db.commit()
    await db.refresh(document)
    return document


@router.get(
    "/borrower/documents/{document_id}/download",
    response_model=DocumentDownload,
    tags=["borrower", "documents"],
)
async def borrower_document_download(document_id: uuid.UUID, db: Db, user: User):
    document = await db.get(models.Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await services.get_authorized_application(db, document.application_id, user)
    if document.status not in {"CLEAN", "APPROVED"}:
        problem(
            "DOCUMENT_NOT_AVAILABLE",
            "The document is not available until security review is complete.",
            409,
        )
    try:
        url = await S3ObjectStorageAdapter().presigned_download(
            object_key=document.storage_key,
            expires_seconds=300,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail="Document storage is unavailable") from exc
    return DocumentDownload(download_url=url, expires_seconds=300)
