import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, services
from app.auth import User, get_current_user
from app.db import get_db
from app.portal_models import (
    PortalConversation,
    PortalNotification,
    PortalTask,
    PortalUploadSession,
)
from app.portal_schemas import (
    UploadSessionComplete,
    UploadSessionCreate,
    UploadSessionIssued,
    UploadSessionRead,
)
from app.portal_security import (
    active_tenant,
    ensure_subject_or_admin,
    ensure_tenant_access,
    require_borrower,
)
from app.upload_service import (
    build_storage_key,
    issue_presigned_upload,
    validate_upload,
    verify_uploaded_object,
)

router = APIRouter(prefix="/borrower", tags=["borrower-portal"])


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


async def _application(
    *,
    application_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    write: bool = False,
) -> models.Application:
    application = await db.get(models.Application, application_id)
    if application is None:
        raise _problem("APPLICATION_NOT_FOUND", "Application was not found.", 404)
    await services.authorize_application(db, application, user, write=write)
    return application


def _application_fields() -> tuple[str, ...]:
    return (
        "id",
        "borrower_id",
        "status",
        "requested_amount",
        "use_of_funds",
        "version",
        "submitted_at",
        "created_at",
        "updated_at",
    )


@router.get("/workspace")
async def borrower_workspace(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    principal = user.principal
    borrower_id = require_borrower(principal)
    application_result = await db.execute(
        select(models.Application)
        .where(models.Application.borrower_id == borrower_id)
        .order_by(models.Application.created_at.desc())
        .limit(50)
    )
    applications = list(application_result.scalars().all())
    tenant_id = active_tenant(principal)
    task_result = await db.execute(
        select(PortalTask)
        .where(
            PortalTask.tenant_id == tenant_id,
            PortalTask.assigned_to_subject == principal.subject,
            PortalTask.status.notin_(["COMPLETED", "CANCELLED"]),
        )
        .order_by(PortalTask.due_at.asc(), PortalTask.created_at.desc())
        .limit(50)
    )
    notification_result = await db.execute(
        select(PortalNotification)
        .where(
            PortalNotification.tenant_id == tenant_id,
            PortalNotification.recipient_subject == principal.subject,
            PortalNotification.read_at.is_(None),
        )
        .order_by(PortalNotification.created_at.desc())
        .limit(25)
    )
    conversation_result = await db.execute(
        select(PortalConversation)
        .where(PortalConversation.tenant_id == tenant_id)
        .order_by(PortalConversation.last_message_at.desc())
        .limit(100)
    )
    conversations = [
        conversation
        for conversation in conversation_result.scalars().all()
        if principal.subject in conversation.participant_subjects
    ][:25]
    return {
        "applications": [
            _public(application, _application_fields()) for application in applications
        ],
        "open_tasks": [
            _public(
                task,
                (
                    "id",
                    "application_id",
                    "task_type",
                    "title",
                    "status",
                    "priority",
                    "due_at",
                    "version",
                    "created_at",
                ),
            )
            for task in task_result.scalars().all()
        ],
        "unread_notifications": [
            _public(
                notification,
                (
                    "id",
                    "notification_type",
                    "title",
                    "body",
                    "href",
                    "created_at",
                ),
            )
            for notification in notification_result.scalars().all()
        ],
        "conversations": [
            _public(
                conversation,
                (
                    "id",
                    "application_id",
                    "topic",
                    "status",
                    "last_message_at",
                ),
            )
            for conversation in conversations
        ],
        "summary": {
            "application_count": len(applications),
            "active_application_count": sum(
                1
                for application in applications
                if getattr(application, "status", "")
                not in {"FUNDED", "DECLINED", "WITHDRAWN", "EXPIRED"}
            ),
        },
    }


@router.get("/applications/{application_id}/workspace")
async def application_workspace(
    application_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    require_borrower(user.principal)
    application = await _application(
        application_id=application_id,
        user=user,
        db=db,
    )
    conditions_result = await db.execute(
        select(models.UnderwritingCondition)
        .where(models.UnderwritingCondition.application_id == application.id)
        .order_by(models.UnderwritingCondition.created_at.asc())
    )
    offers_result = await db.execute(
        select(models.Offer)
        .where(models.Offer.application_id == application.id)
        .order_by(models.Offer.created_at.desc())
    )
    documents_result = await db.execute(
        select(models.Document)
        .where(models.Document.application_id == application.id)
        .order_by(models.Document.created_at.desc())
    )
    bank_result = await db.execute(
        select(models.BankConnection)
        .where(models.BankConnection.application_id == application.id)
        .order_by(models.BankConnection.created_at.desc())
    )
    task_result = await db.execute(
        select(PortalTask)
        .where(PortalTask.application_id == application.id)
        .order_by(PortalTask.created_at.desc())
    )
    upload_result = await db.execute(
        select(PortalUploadSession)
        .where(PortalUploadSession.application_id == application.id)
        .order_by(PortalUploadSession.created_at.desc())
        .limit(100)
    )
    return {
        "application": _public(application, _application_fields()),
        "conditions": [
            _public(
                condition,
                (
                    "id",
                    "condition_type",
                    "title",
                    "description",
                    "status",
                    "due_at",
                    "satisfied_at",
                    "created_at",
                ),
            )
            for condition in conditions_result.scalars().all()
        ],
        "offers": [
            _public(
                offer,
                (
                    "id",
                    "lender_id",
                    "status",
                    "amount",
                    "term_months",
                    "interest_rate",
                    "factor_rate",
                    "payment_amount",
                    "payment_frequency",
                    "expires_at",
                    "created_at",
                ),
            )
            for offer in offers_result.scalars().all()
        ],
        "documents": [
            _public(
                document,
                (
                    "id",
                    "document_type",
                    "file_name",
                    "original_file_name",
                    "status",
                    "scan_status",
                    "size_bytes",
                    "created_at",
                ),
            )
            for document in documents_result.scalars().all()
        ],
        "bank_connections": [
            _public(
                connection,
                (
                    "id",
                    "provider",
                    "status",
                    "institution_name",
                    "last_synced_at",
                    "created_at",
                ),
            )
            for connection in bank_result.scalars().all()
        ],
        "tasks": [
            _public(
                task,
                (
                    "id",
                    "task_type",
                    "title",
                    "description",
                    "status",
                    "priority",
                    "due_at",
                    "version",
                    "created_at",
                ),
            )
            for task in task_result.scalars().all()
        ],
        "upload_sessions": [
            UploadSessionRead.model_validate(session).model_dump(mode="json")
            for session in upload_result.scalars().all()
        ],
    }


@router.get("/uploads", response_model=list[UploadSessionRead])
async def list_upload_sessions(
    application_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=250),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortalUploadSession]:
    principal = user.principal
    require_borrower(principal)
    query = select(PortalUploadSession).where(
        PortalUploadSession.tenant_id == active_tenant(principal),
        PortalUploadSession.created_by_subject == principal.subject,
    )
    if application_id:
        await _application(application_id=application_id, user=user, db=db)
        query = query.where(PortalUploadSession.application_id == application_id)
    result = await db.execute(
        query.order_by(PortalUploadSession.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.post(
    "/applications/{application_id}/uploads",
    response_model=UploadSessionIssued,
    status_code=201,
)
async def create_upload_session(
    application_id: uuid.UUID,
    payload: UploadSessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UploadSessionIssued:
    principal = user.principal
    require_borrower(principal)
    await services.require_capability(db, "documents.secure_upload")
    application = await _application(
        application_id=application_id,
        user=user,
        db=db,
        write=True,
    )
    validate_upload(payload)
    session_id = uuid.uuid4()
    tenant_id = active_tenant(principal)
    storage_key = build_storage_key(
        tenant_id=tenant_id,
        application_id=application.id,
        session_id=session_id,
        original_file_name=payload.original_file_name,
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    session = PortalUploadSession(
        id=session_id,
        tenant_id=tenant_id,
        application_id=application.id,
        owner_id=payload.owner_id,
        condition_id=payload.condition_id,
        document_type=payload.document_type.upper(),
        original_file_name=payload.original_file_name,
        mime_type=payload.mime_type.lower(),
        size_bytes=payload.size_bytes,
        sha256=payload.sha256.lower(),
        storage_key=storage_key,
        created_by_subject=principal.subject,
        expires_at=expires_at,
        metadata_payload={
            **payload.metadata_payload,
            "scan_required": True,
            "download_exposed": False,
        },
    )
    issued = issue_presigned_upload(
        storage_key=storage_key,
        mime_type=session.mime_type,
        size_bytes=session.size_bytes,
        sha256=session.sha256,
        session_id=session.id,
        expires_seconds=900,
    )
    db.add(session)
    await db.flush()
    db.add(
        _construct(
            models.AuditEvent,
            {
                "actor_subject": principal.subject,
                "action": "borrower_upload_session.created",
                "entity_type": "portal_upload_session",
                "entity_id": session.id,
                "details": {
                    "application_id": str(application.id),
                    "document_type": session.document_type,
                    "size_bytes": session.size_bytes,
                    "organization_id": str(tenant_id),
                },
            },
        )
    )
    await db.commit()
    await db.refresh(session)
    return UploadSessionIssued(
        session=UploadSessionRead.model_validate(session),
        upload_url=issued.url,
        upload_headers=issued.headers,
    )


@router.post("/uploads/{session_id}/complete")
async def complete_upload_session(
    session_id: uuid.UUID,
    payload: UploadSessionComplete,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    principal = user.principal
    require_borrower(principal)
    await services.require_capability(db, "documents.secure_upload")
    session = await db.get(PortalUploadSession, session_id)
    if session is None:
        raise _problem(
            "UPLOAD_SESSION_NOT_FOUND",
            "Upload session was not found.",
            404,
        )
    ensure_tenant_access(principal, session.tenant_id)
    ensure_subject_or_admin(principal, session.created_by_subject)
    if session.status != "PENDING":
        raise _problem(
            "UPLOAD_SESSION_ALREADY_COMPLETED",
            "This upload session can no longer be completed.",
            409,
        )
    if session.expires_at < datetime.now(UTC):
        session.status = "EXPIRED"
        await db.commit()
        raise _problem("UPLOAD_SESSION_EXPIRED", "Upload session expired.", 409)
    await _application(
        application_id=session.application_id,
        user=user,
        db=db,
        write=True,
    )
    verified = verify_uploaded_object(
        storage_key=session.storage_key,
        expected_size=session.size_bytes,
        expected_sha256=session.sha256,
        expected_session_id=session.id,
    )
    document = _construct(
        models.Document,
        {
            "application_id": session.application_id,
            "owner_id": session.owner_id,
            "condition_id": session.condition_id,
            "document_type": session.document_type,
            "file_name": session.original_file_name,
            "original_file_name": session.original_file_name,
            "mime_type": session.mime_type,
            "content_type": session.mime_type,
            "size_bytes": session.size_bytes,
            "sha256": session.sha256,
            "storage_key": session.storage_key,
            "status": "QUARANTINED",
            "scan_status": "PENDING",
            "uploaded_by": principal.subject,
            "uploaded_by_subject": principal.subject,
        },
    )
    db.add(document)
    await db.flush()
    session.status = "QUARANTINED"
    session.completed_at = datetime.now(UTC)
    session.provider_etag = payload.provider_etag or verified.etag
    db.add(
        _construct(
            models.OutboxEvent,
            {
                "event_type": "DocumentQuarantined",
                "aggregate_type": "application",
                "aggregate_id": session.application_id,
                "payload": {
                    "document_id": str(document.id),
                    "application_id": str(session.application_id),
                    "upload_session_id": str(session.id),
                    "scan_required": True,
                },
                "status": "PENDING",
            },
        )
    )
    db.add(
        _construct(
            models.AuditEvent,
            {
                "actor_subject": principal.subject,
                "action": "borrower_document.quarantined",
                "entity_type": "document",
                "entity_id": document.id,
                "details": {
                    "application_id": str(session.application_id),
                    "upload_session_id": str(session.id),
                    "organization_id": str(session.tenant_id),
                    "sha256": session.sha256,
                },
            },
        )
    )
    await db.commit()
    await db.refresh(document)
    await db.refresh(session)
    return {
        "document": _public(
            document,
            (
                "id",
                "application_id",
                "document_type",
                "file_name",
                "original_file_name",
                "status",
                "scan_status",
                "size_bytes",
                "created_at",
            ),
        ),
        "upload_session": UploadSessionRead.model_validate(session).model_dump(
            mode="json"
        ),
        "download_available": False,
        "next_state": "MALWARE_SCAN_PENDING",
    }
