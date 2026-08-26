from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import identity_models, services
from app.auth import Principal, get_current_user
from app.db import get_db
from app.portal_models import (
    PortalConversation,
    PortalMessage,
    PortalNotification,
    PortalTask,
    PortalUploadSession,
)
from app.portal_permissions import (
    build_navigation,
    has_permission,
    require_active_organization,
    require_any_permission,
)
from app.portal_schemas import (
    NavigationItemRead,
    PortalContextRead,
    PortalConversationCreate,
    PortalConversationRead,
    PortalMessageCreate,
    PortalMessageRead,
    PortalNotificationCreate,
    PortalNotificationRead,
    PortalTaskPatch,
    PortalTaskRead,
    UploadSessionComplete,
    UploadSessionCreate,
    UploadSessionRead,
)
from app.portal_storage import (
    PortalStorageUnavailable,
    PortalStorageVerificationError,
    create_presigned_upload,
    verify_uploaded_object,
)

router = APIRouter(tags=["portal"])


ALLOWED_UPLOAD_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _not_found(resource: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "NOT_FOUND", "message": f"{resource} was not found."},
    )


def _organization_id(principal: Principal) -> uuid.UUID:
    return require_active_organization(principal)


def _can_manage_portal_work(principal: Principal) -> bool:
    return has_permission(
        principal,
        "*",
        "task.manage",
        "lead.update",
        "underwriting.review",
        "capability.manage",
    )


def _authorized_conversation(
    db: Session,
    principal: Principal,
    conversation_id: uuid.UUID,
) -> PortalConversation:
    organization_id = _organization_id(principal)
    conversation = db.scalar(
        select(PortalConversation).where(
            PortalConversation.id == conversation_id,
            PortalConversation.organization_id == organization_id,
        )
    )
    if conversation is None:
        raise _not_found("Conversation")
    return conversation


def _upload_read(
    session: PortalUploadSession,
    *,
    upload_url: str | None = None,
    upload_headers: dict[str, str] | None = None,
    upload_token: str | None = None,
) -> UploadSessionRead:
    return UploadSessionRead(
        id=session.id,
        application_id=session.application_id,
        original_file_name=session.original_file_name,
        mime_type=session.mime_type,
        size_bytes=session.size_bytes,
        sha256=session.sha256,
        status=session.status,
        scan_status=session.scan_status,
        expires_at=session.expires_at,
        completed_at=session.completed_at,
        upload_url=upload_url,
        upload_headers=upload_headers or {},
        upload_token=upload_token,
    )


@router.get("/auth/context", response_model=PortalContextRead)
def auth_context(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    active_organization_id = _organization_id(principal)
    organizations = list(
        db.scalars(
            select(identity_models.Organization)
            .where(identity_models.Organization.id.in_(principal.organization_ids))
            .order_by(identity_models.Organization.name)
        )
    )
    return PortalContextRead(
        user_id=principal.user_id,
        active_organization_id=active_organization_id,
        organizations=organizations,
        roles=sorted(principal.roles),
        permissions=sorted(principal.permissions),
        membership_types=sorted(principal.membership_types),
        navigation=[NavigationItemRead(**item) for item in build_navigation(principal)],
        capabilities=services.effective_capabilities(db),
    )


@router.get("/portal/navigation", response_model=list[NavigationItemRead])
def portal_navigation(
    principal: Annotated[Principal, Depends(get_current_user)],
):
    _organization_id(principal)
    return [NavigationItemRead(**item) for item in build_navigation(principal)]


@router.get("/portal/tasks", response_model=list[PortalTaskRead])
def list_portal_tasks(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    task_status: str | None = Query(default=None, alias="status", max_length=40),
    limit: int = Query(default=100, ge=1, le=250),
):
    organization_id = _organization_id(principal)
    statement = select(PortalTask).where(PortalTask.organization_id == organization_id)
    if not _can_manage_portal_work(principal):
        statement = statement.where(
            or_(
                PortalTask.assignee_user_id == principal.user_id,
                PortalTask.created_by_user_id == principal.user_id,
            )
        )
    if task_status:
        statement = statement.where(PortalTask.status == task_status.upper())
    return list(
        db.scalars(statement.order_by(PortalTask.created_at.desc()).limit(limit))
    )


@router.patch("/portal/tasks/{task_id}", response_model=PortalTaskRead)
def patch_portal_task(
    task_id: uuid.UUID,
    payload: PortalTaskPatch,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    organization_id = _organization_id(principal)
    task = db.scalar(
        select(PortalTask).where(
            PortalTask.id == task_id,
            PortalTask.organization_id == organization_id,
        )
    )
    if task is None:
        raise _not_found("Task")
    if not _can_manage_portal_work(principal) and task.assignee_user_id != principal.user_id:
        raise _not_found("Task")
    if task.version != payload.version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VERSION_CONFLICT",
                "message": "The task changed after it was loaded.",
                "context": {"current_version": task.version},
            },
        )
    if payload.assignee_user_id is not None:
        require_any_permission(principal, "task.manage", "lead.update", "*")
        task.assignee_user_id = payload.assignee_user_id
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.due_at is not None:
        task.due_at = payload.due_at
    if payload.status is not None:
        task.status = payload.status
        task.completed_at = datetime.now(UTC) if payload.status == "COMPLETED" else None
    task.version += 1
    db.commit()
    db.refresh(task)
    return task


@router.get("/portal/notifications", response_model=list[PortalNotificationRead])
def list_notifications(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    unread_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=250),
):
    organization_id = _organization_id(principal)
    statement = select(PortalNotification).where(
        PortalNotification.organization_id == organization_id,
        PortalNotification.user_id == principal.user_id,
    )
    if unread_only:
        statement = statement.where(PortalNotification.read_at.is_(None))
    return list(
        db.scalars(
            statement.order_by(PortalNotification.created_at.desc()).limit(limit)
        )
    )


@router.post(
    "/portal/notifications",
    response_model=PortalNotificationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_notification(
    payload: PortalNotificationCreate,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    require_any_permission(principal, "notification.send", "lead.update", "*")
    notification = PortalNotification(
        organization_id=_organization_id(principal),
        user_id=payload.user_id,
        notification_type=payload.notification_type,
        title=payload.title,
        body=payload.body,
        action_url=payload.action_url,
        metadata_payload=payload.metadata_payload,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


@router.post(
    "/portal/notifications/{notification_id}/read",
    response_model=PortalNotificationRead,
)
def mark_notification_read(
    notification_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    notification = db.scalar(
        select(PortalNotification).where(
            PortalNotification.id == notification_id,
            PortalNotification.organization_id == _organization_id(principal),
            PortalNotification.user_id == principal.user_id,
        )
    )
    if notification is None:
        raise _not_found("Notification")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
        db.refresh(notification)
    return notification


@router.get("/portal/conversations", response_model=list[PortalConversationRead])
def list_conversations(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    application_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=250),
):
    statement = select(PortalConversation).where(
        PortalConversation.organization_id == _organization_id(principal)
    )
    if application_id is not None:
        statement = statement.where(PortalConversation.application_id == application_id)
    return list(
        db.scalars(
            statement.order_by(PortalConversation.updated_at.desc()).limit(limit)
        )
    )


@router.post(
    "/portal/conversations",
    response_model=PortalConversationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    payload: PortalConversationCreate,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if payload.application_id is not None and "BORROWER" in principal.membership_types:
        services.get_authorized_application(db, principal, payload.application_id)
    conversation = PortalConversation(
        organization_id=_organization_id(principal),
        application_id=payload.application_id,
        created_by_user_id=principal.user_id,
        subject=payload.subject,
    )
    db.add(conversation)
    db.flush()
    if payload.first_message:
        db.add(
            PortalMessage(
                conversation_id=conversation.id,
                sender_user_id=principal.user_id,
                body=payload.first_message,
            )
        )
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get(
    "/portal/conversations/{conversation_id}/messages",
    response_model=list[PortalMessageRead],
)
def list_messages(
    conversation_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=200, ge=1, le=500),
):
    _authorized_conversation(db, principal, conversation_id)
    return list(
        db.scalars(
            select(PortalMessage)
            .where(PortalMessage.conversation_id == conversation_id)
            .order_by(PortalMessage.created_at.asc())
            .limit(limit)
        )
    )


@router.post(
    "/portal/conversations/{conversation_id}/messages",
    response_model=PortalMessageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_message(
    conversation_id: uuid.UUID,
    payload: PortalMessageCreate,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    conversation = _authorized_conversation(db, principal, conversation_id)
    if conversation.status != "OPEN":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONVERSATION_CLOSED",
                "message": "Messages cannot be added to a closed conversation.",
            },
        )
    message = PortalMessage(
        conversation_id=conversation.id,
        sender_user_id=principal.user_id,
        body=payload.body,
        attachment_document_id=payload.attachment_document_id,
        metadata_payload=payload.metadata_payload,
    )
    conversation.updated_at = datetime.now(UTC)
    conversation.version += 1
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


@router.get(
    "/portal/applications/{application_id}/upload-sessions",
    response_model=list[UploadSessionRead],
)
def list_upload_sessions(
    application_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    services.get_authorized_application(db, principal, application_id)
    sessions = db.scalars(
        select(PortalUploadSession)
        .where(
            PortalUploadSession.organization_id == _organization_id(principal),
            PortalUploadSession.application_id == application_id,
        )
        .order_by(PortalUploadSession.created_at.desc())
    )
    return [_upload_read(item) for item in sessions]


@router.post(
    "/portal/applications/{application_id}/upload-sessions",
    response_model=UploadSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_upload_session(
    application_id: uuid.UUID,
    payload: UploadSessionCreate,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    services.get_authorized_application(db, principal, application_id)
    services.require_capability(db, "documents.secure_upload")
    if payload.mime_type.lower() not in ALLOWED_UPLOAD_MIME_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_FILE_TYPE",
                "message": "The document type is not accepted.",
            },
        )

    session_id = uuid.uuid4()
    upload_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(upload_token.encode("utf-8")).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", payload.original_file_name)
    object_key = (
        f"quarantine/{_organization_id(principal)}/{application_id}/"
        f"{session_id}/{uuid.uuid4()}-{safe_name}"
    )
    try:
        descriptor = create_presigned_upload(
            object_key=object_key,
            content_type=payload.mime_type,
            sha256=payload.sha256,
        )
    except PortalStorageUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DOCUMENT_STORAGE_UNAVAILABLE",
                "message": "Secure document storage is not configured or unavailable.",
            },
        ) from exc

    upload_session = PortalUploadSession(
        id=session_id,
        organization_id=_organization_id(principal),
        application_id=application_id,
        requested_by_user_id=principal.user_id,
        original_file_name=payload.original_file_name,
        mime_type=payload.mime_type.lower(),
        size_bytes=payload.size_bytes,
        sha256=payload.sha256,
        object_key=object_key,
        upload_token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.add(upload_session)
    db.commit()
    db.refresh(upload_session)
    return _upload_read(
        upload_session,
        upload_url=descriptor.url,
        upload_headers=descriptor.headers,
        upload_token=upload_token,
    )


@router.post(
    "/portal/upload-sessions/{session_id}/complete",
    response_model=UploadSessionRead,
)
async def complete_upload_session(
    session_id: uuid.UUID,
    payload: UploadSessionComplete,
    upload_token: Annotated[str, Header(alias="X-Upload-Token")],
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    upload_session = db.scalar(
        select(PortalUploadSession).where(
            PortalUploadSession.id == session_id,
            PortalUploadSession.organization_id == _organization_id(principal),
            PortalUploadSession.requested_by_user_id == principal.user_id,
        )
    )
    if upload_session is None:
        raise _not_found("Upload session")
    if not secrets.compare_digest(
        upload_session.upload_token_hash,
        hashlib.sha256(upload_token.encode("utf-8")).hexdigest(),
    ):
        raise _not_found("Upload session")
    if upload_session.version != payload.version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VERSION_CONFLICT",
                "message": "The upload session changed after it was loaded.",
                "context": {"current_version": upload_session.version},
            },
        )
    if upload_session.status == "QUARANTINED":
        return _upload_read(upload_session)
    if upload_session.expires_at <= datetime.now(UTC):
        upload_session.status = "EXPIRED"
        upload_session.version += 1
        db.commit()
        raise HTTPException(
            status_code=410,
            detail={"code": "UPLOAD_SESSION_EXPIRED", "message": "Upload expired."},
        )

    try:
        await asyncio.to_thread(
            verify_uploaded_object,
            object_key=upload_session.object_key,
            expected_size=upload_session.size_bytes,
            expected_sha256=upload_session.sha256,
        )
    except PortalStorageVerificationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UPLOAD_VERIFICATION_FAILED",
                "message": "The uploaded object did not pass integrity verification.",
            },
        ) from exc

    upload_session.status = "QUARANTINED"
    upload_session.scan_status = "PENDING"
    upload_session.completed_at = datetime.now(UTC)
    upload_session.version += 1
    db.commit()
    db.refresh(upload_session)
    return _upload_read(upload_session)
