from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, services
from app.auth import Principal, get_current_user
from app.db import get_db
from app.portal_models import (
    PortalConversation,
    PortalNotification,
    PortalTask,
    PortalUploadSession,
)
from app.portal_permissions import require_active_organization

router = APIRouter(prefix="/borrower", tags=["borrower-portal"])


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


def _require_borrower(principal: Principal) -> uuid.UUID:
    if principal.borrower_id is None or "BORROWER" not in principal.membership_types:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "BORROWER_CONTEXT_REQUIRED",
                "message": "An active borrower membership is required.",
            },
        )
    require_active_organization(principal)
    return principal.borrower_id


def _application_read(application: Any) -> dict[str, Any]:
    return _record(
        application,
        (
            "id",
            "application_number",
            "business_name",
            "status",
            "requested_amount",
            "approved_amount",
            "purpose",
            "term_months",
            "progress_percent",
            "submitted_at",
            "created_at",
            "updated_at",
            "version",
        ),
    )


def _offer_read(offer: Any) -> dict[str, Any]:
    return _record(
        offer,
        (
            "id",
            "application_id",
            "lender_id",
            "status",
            "amount",
            "approved_amount",
            "interest_rate",
            "apr",
            "term_months",
            "monthly_payment",
            "origination_fee",
            "expires_at",
            "created_at",
            "updated_at",
            "version",
        ),
    )


def _document_read(document: Any) -> dict[str, Any]:
    result = _record(
        document,
        (
            "id",
            "application_id",
            "document_type",
            "status",
            "original_file_name",
            "file_name",
            "mime_type",
            "size_bytes",
            "scan_status",
            "reviewed_at",
            "created_at",
            "updated_at",
            "version",
        ),
    )
    result.pop("storage_key", None)
    result.pop("object_key", None)
    return result


@router.get("/workspace")
def borrower_workspace(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    application_limit: int = Query(default=25, ge=1, le=100),
):
    borrower_id = _require_borrower(principal)
    organization_id = require_active_organization(principal)

    applications = list(
        db.scalars(
            select(models.Application)
            .where(models.Application.borrower_id == borrower_id)
            .order_by(models.Application.updated_at.desc())
            .limit(application_limit)
        )
    )
    application_ids = [application.id for application in applications]

    task_statement = select(PortalTask).where(
        PortalTask.organization_id == organization_id,
        PortalTask.assignee_user_id == principal.user_id,
        PortalTask.status.in_(("OPEN", "IN_PROGRESS", "BLOCKED")),
    )
    if application_ids:
        task_statement = task_statement.where(
            PortalTask.application_id.in_(application_ids)
        )
    tasks = list(
        db.scalars(task_statement.order_by(PortalTask.created_at.desc()).limit(100))
    )

    notifications = list(
        db.scalars(
            select(PortalNotification)
            .where(
                PortalNotification.organization_id == organization_id,
                PortalNotification.user_id == principal.user_id,
                PortalNotification.read_at.is_(None),
            )
            .order_by(PortalNotification.created_at.desc())
            .limit(50)
        )
    )
    conversations = list(
        db.scalars(
            select(PortalConversation)
            .where(PortalConversation.organization_id == organization_id)
            .order_by(PortalConversation.updated_at.desc())
            .limit(25)
        )
    )

    active = [item for item in applications if getattr(item, "status", None) not in {"FUNDED", "DECLINED", "WITHDRAWN", "CANCELLED"}]
    return {
        "principal": {
            "user_id": str(principal.user_id),
            "borrower_id": str(borrower_id),
            "organization_id": str(organization_id),
        },
        "summary": {
            "application_count": len(applications),
            "active_application_count": len(active),
            "open_task_count": len(tasks),
            "unread_notification_count": len(notifications),
            "conversation_count": len(conversations),
        },
        "applications": [_application_read(item) for item in applications],
        "tasks": [
            _record(
                item,
                (
                    "id",
                    "application_id",
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
            for item in tasks
        ],
        "notifications": [
            _record(
                item,
                (
                    "id",
                    "notification_type",
                    "title",
                    "body",
                    "action_url",
                    "created_at",
                ),
            )
            for item in notifications
        ],
        "conversations": [
            _record(
                item,
                (
                    "id",
                    "application_id",
                    "subject",
                    "status",
                    "version",
                    "updated_at",
                ),
            )
            for item in conversations
        ],
    }


@router.get("/applications/{application_id}/summary")
def borrower_application_summary(
    application_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_borrower(principal)
    application = services.get_authorized_application(db, principal, application_id)

    offers = list(
        db.scalars(
            select(models.Offer)
            .where(models.Offer.application_id == application_id)
            .order_by(models.Offer.created_at.desc())
        )
    )
    documents = list(
        db.scalars(
            select(models.Document)
            .where(models.Document.application_id == application_id)
            .order_by(models.Document.created_at.desc())
        )
    )
    tasks = list(
        db.scalars(
            select(PortalTask)
            .where(
                PortalTask.organization_id == require_active_organization(principal),
                PortalTask.application_id == application_id,
                PortalTask.assignee_user_id == principal.user_id,
            )
            .order_by(PortalTask.created_at.desc())
        )
    )
    upload_sessions = list(
        db.scalars(
            select(PortalUploadSession)
            .where(
                PortalUploadSession.organization_id
                == require_active_organization(principal),
                PortalUploadSession.application_id == application_id,
            )
            .order_by(PortalUploadSession.created_at.desc())
        )
    )

    accepted_offer = next(
        (offer for offer in offers if getattr(offer, "status", None) == "ACCEPTED"),
        None,
    )
    return {
        "application": _application_read(application),
        "summary": {
            "offer_count": len(offers),
            "document_count": len(documents),
            "open_task_count": sum(
                1 for task in tasks if task.status not in {"COMPLETED", "CANCELLED"}
            ),
            "pending_upload_count": sum(
                1
                for upload in upload_sessions
                if upload.status not in {"QUARANTINED", "EXPIRED", "CANCELLED"}
            ),
            "accepted_offer_id": str(accepted_offer.id) if accepted_offer else None,
        },
        "offers": [_offer_read(item) for item in offers],
        "documents": [_document_read(item) for item in documents],
        "tasks": [
            _record(
                item,
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
            for item in tasks
        ],
        "upload_sessions": [
            _record(
                item,
                (
                    "id",
                    "original_file_name",
                    "mime_type",
                    "size_bytes",
                    "sha256",
                    "status",
                    "scan_status",
                    "expires_at",
                    "completed_at",
                    "version",
                    "created_at",
                ),
            )
            for item in upload_sessions
        ],
    }


@router.get("/applications/{application_id}/offers")
def borrower_offer_center(
    application_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_borrower(principal)
    services.get_authorized_application(db, principal, application_id)
    offers = db.scalars(
        select(models.Offer)
        .where(models.Offer.application_id == application_id)
        .order_by(models.Offer.created_at.desc())
    )
    return {"items": [_offer_read(item) for item in offers]}


@router.get("/applications/{application_id}/documents")
def borrower_document_center(
    application_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_borrower(principal)
    services.get_authorized_application(db, principal, application_id)
    documents = db.scalars(
        select(models.Document)
        .where(models.Document.application_id == application_id)
        .order_by(models.Document.created_at.desc())
    )
    upload_sessions = db.scalars(
        select(PortalUploadSession)
        .where(
            PortalUploadSession.organization_id == require_active_organization(principal),
            PortalUploadSession.application_id == application_id,
        )
        .order_by(PortalUploadSession.created_at.desc())
    )
    return {
        "documents": [_document_read(item) for item in documents],
        "upload_sessions": [
            _record(
                item,
                (
                    "id",
                    "original_file_name",
                    "mime_type",
                    "size_bytes",
                    "sha256",
                    "status",
                    "scan_status",
                    "expires_at",
                    "completed_at",
                    "version",
                    "created_at",
                ),
            )
            for item in upload_sessions
        ],
    }


@router.get("/applications/{application_id}/communication")
def borrower_communication_center(
    application_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _require_borrower(principal)
    services.get_authorized_application(db, principal, application_id)
    conversations = db.scalars(
        select(PortalConversation)
        .where(
            PortalConversation.organization_id == require_active_organization(principal),
            PortalConversation.application_id == application_id,
        )
        .order_by(PortalConversation.updated_at.desc())
    )
    return {
        "items": [
            _record(
                item,
                (
                    "id",
                    "subject",
                    "status",
                    "version",
                    "created_at",
                    "updated_at",
                ),
            )
            for item in conversations
        ]
    }
