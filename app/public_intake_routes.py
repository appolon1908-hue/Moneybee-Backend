from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.auth import Principal, require_permission
from app.config import settings
from app.db import get_db
from app.integration_models import IntegrationInboxMessage
from app.public_intake_models import PublicIntake, PublicIntakeConsent
from app.public_intake_schemas import (
    CallbackRequestInput,
    ContactRequestInput,
    DealSubmissionInquiryInput,
    DeliveryRequeue,
    LenderPartnerInquiryInput,
    PublicIntakeAccepted,
    ReferralPartnerInquiryInput,
)
from app.public_intake_service import create_public_intake


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=160),
]


async def _receive(
    *,
    intake_type: str,
    payload: Any,
    request: Request,
    db: AsyncSession,
    idempotency_key: str,
) -> PublicIntakeAccepted:
    return await create_public_intake(
        db,
        intake_type=intake_type,
        payload=payload,
        request=request,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/public/contact-requests",
    response_model=PublicIntakeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["public-intake"],
)
async def contact_request(
    payload: ContactRequestInput,
    request: Request,
    db: Db,
    idempotency_key: IdempotencyKey,
):
    return await _receive(
        intake_type="CONTACT_REQUEST",
        payload=payload,
        request=request,
        db=db,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/public/callback-requests",
    response_model=PublicIntakeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["public-intake"],
)
async def callback_request(
    payload: CallbackRequestInput,
    request: Request,
    db: Db,
    idempotency_key: IdempotencyKey,
):
    return await _receive(
        intake_type="CALLBACK_REQUEST",
        payload=payload,
        request=request,
        db=db,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/public/lender-partner-inquiries",
    response_model=PublicIntakeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["public-intake"],
)
async def lender_partner_inquiry(
    payload: LenderPartnerInquiryInput,
    request: Request,
    db: Db,
    idempotency_key: IdempotencyKey,
):
    return await _receive(
        intake_type="LENDER_PARTNER_INQUIRY",
        payload=payload,
        request=request,
        db=db,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/public/referral-partner-inquiries",
    response_model=PublicIntakeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["public-intake"],
)
async def referral_partner_inquiry(
    payload: ReferralPartnerInquiryInput,
    request: Request,
    db: Db,
    idempotency_key: IdempotencyKey,
):
    return await _receive(
        intake_type="REFERRAL_PARTNER_INQUIRY",
        payload=payload,
        request=request,
        db=db,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/public/deal-submission-inquiries",
    response_model=PublicIntakeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["public-intake"],
)
async def deal_submission_inquiry(
    payload: DealSubmissionInquiryInput,
    request: Request,
    db: Db,
    idempotency_key: IdempotencyKey,
):
    return await _receive(
        intake_type="DEAL_SUBMISSION_INQUIRY",
        payload=payload,
        request=request,
        db=db,
        idempotency_key=idempotency_key,
    )


def _delivery_summary(event: models.OutboxEvent) -> dict[str, Any]:
    payload = event.payload or {}
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": str(event.aggregate_id),
        "status": event.status.value if hasattr(event.status, "value") else str(event.status),
        "attempt_count": event.attempt_count,
        "provider": event.provider,
        "destination": event.destination,
        "last_http_status": event.last_http_status,
        "last_error_code": event.last_error_code,
        "last_error": event.last_error,
        "next_attempt_at": event.next_attempt_at,
        "delivered_at": event.delivered_at,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
        "reference": payload.get("reference"),
        "intake_type": payload.get("intake_type"),
        "moneybee_intake_id": payload.get("moneybee_intake_id"),
    }


def _crm_event_filter():
    return or_(
        models.OutboxEvent.destination == "codestra:crm-projection",
        models.OutboxEvent.event_type.like("public.%"),
    )


@router.get("/admin/crm-deliveries", tags=["admin", "integrations"])
async def crm_deliveries(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.read"))],
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    statement = select(models.OutboxEvent).where(_crm_event_filter())
    if status_filter:
        try:
            parsed_status = models.OutboxStatus(status_filter.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid CRM delivery status") from exc
        statement = statement.where(models.OutboxEvent.status == parsed_status)
    rows = (
        await db.scalars(
            statement.order_by(models.OutboxEvent.created_at.desc()).limit(limit)
        )
    ).all()
    return [_delivery_summary(row) for row in rows]


@router.get("/admin/crm-deliveries/{delivery_id}", tags=["admin", "integrations"])
async def crm_delivery(
    delivery_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.read"))],
):
    row = await db.scalar(
        select(models.OutboxEvent).where(
            models.OutboxEvent.id == delivery_id,
            _crm_event_filter(),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="CRM delivery not found")
    return _delivery_summary(row)


@router.post(
    "/admin/crm-deliveries/{delivery_id}/requeue",
    tags=["admin", "integrations"],
)
async def requeue_crm_delivery(
    delivery_id: uuid.UUID,
    payload: DeliveryRequeue,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.manage"))],
):
    row = await db.scalar(
        select(models.OutboxEvent)
        .where(models.OutboxEvent.id == delivery_id, _crm_event_filter())
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="CRM delivery not found")
    if row.status == models.OutboxStatus.DELIVERED:
        raise HTTPException(status_code=409, detail="Delivered CRM events cannot be requeued")
    if row.status == models.OutboxStatus.LEASED:
        raise HTTPException(status_code=409, detail="The CRM event is currently leased")
    row.status = models.OutboxStatus.PENDING
    row.next_attempt_at = None
    row.lease_owner = None
    row.lease_expires_at = None
    row.last_error = None
    row.last_error_code = None
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="CRM_DELIVERY_REQUEUED",
            resource_type="outbox_event",
            resource_id=str(row.id),
            details={"reason": payload.reason, "event_type": row.event_type},
        )
    )
    await db.commit()
    await db.refresh(row)
    return _delivery_summary(row)


@router.get("/admin/public-intakes", tags=["admin", "integrations"])
async def public_intakes(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
    intake_type: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    statement = select(PublicIntake)
    if intake_type:
        statement = statement.where(PublicIntake.intake_type == intake_type.upper())
    rows = (
        await db.scalars(statement.order_by(PublicIntake.created_at.desc()).limit(limit))
    ).all()
    return [
        {
            "id": str(row.id),
            "reference": row.reference,
            "intake_type": row.intake_type,
            "status": row.status,
            "business_name": row.business_name,
            "contact_name": f"{row.first_name} {row.last_name}".strip(),
            "email": row.email,
            "phone": row.phone,
            "subject": row.subject,
            "attribution": row.attribution,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/admin/public-intakes/{intake_id}", tags=["admin", "integrations"])
async def public_intake_detail(
    intake_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    row = await db.get(PublicIntake, intake_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Public intake not found")
    consents = list(
        (
            await db.scalars(
                select(PublicIntakeConsent).where(
                    PublicIntakeConsent.public_intake_id == intake_id
                )
            )
        ).all()
    )
    return {
        "id": str(row.id),
        "reference": row.reference,
        "intake_type": row.intake_type,
        "status": row.status,
        "contact": {
            "first_name": row.first_name,
            "last_name": row.last_name,
            "email": row.email,
            "phone": row.phone,
        },
        "business_name": row.business_name,
        "subject": row.subject,
        "message": row.message,
        "details": row.details,
        "attribution": row.attribution,
        "source_evidence": row.source_evidence,
        "consents": [
            {
                "id": str(item.id),
                "type": item.consent_type,
                "document_version": item.document_version,
                "document_hash": item.document_hash,
                "accepted": item.accepted,
                "evidence": item.evidence,
            }
            for item in consents
        ],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _verify_codestra_signature(
    raw_body: bytes,
    signature: str | None,
    timestamp: str | None,
) -> bool:
    secret = settings.codestra_middleware_webhook_secret
    if not signature or not timestamp or not secret:
        return False
    try:
        timestamp_value = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - timestamp_value) > settings.codestra_middleware_webhook_tolerance_seconds:
        return False
    expected = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


@router.post(
    "/webhooks/codestra/receipts",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks"],
)
async def codestra_receipt(
    request: Request,
    db: Db,
    signature: Annotated[str | None, Header(alias="X-Codestra-Signature")] = None,
    timestamp_header: Annotated[str | None, Header(alias="X-Codestra-Timestamp")] = None,
    message_header: Annotated[str | None, Header(alias="X-Codestra-Message-Id")] = None,
):
    body = await request.body()
    if settings.middleware_provider != "codestra":
        raise HTTPException(status_code=503, detail="Codestra middleware is disabled")
    if len(body) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    if not _verify_codestra_signature(body, signature, timestamp_header):
        raise HTTPException(status_code=401, detail="Invalid Codestra signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    payload_hash = hashlib.sha256(body).hexdigest()
    message_id = str(
        message_header
        or payload.get("message_id")
        or payload.get("receipt_id")
        or payload.get("event_id")
        or f"sha256:{payload_hash}"
    )[:255]
    existing = await db.scalar(
        select(IntegrationInboxMessage).where(
            IntegrationInboxMessage.provider == "codestra",
            IntegrationInboxMessage.event_id == message_id,
        )
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CODESTRA_MESSAGE_ID_CONFLICT",
                    "message": "The message ID was already received with a different payload.",
                },
            )
        return {"received": True, "duplicate": True, "message_id": message_id}

    event_type = str(payload.get("event_type") or payload.get("type") or "crm.delivery.receipt")
    inbox = IntegrationInboxMessage(
        provider="codestra",
        event_id=message_id,
        event_type=event_type[:160],
        tenant_id=str(payload.get("tenant_id")) if payload.get("tenant_id") else None,
        payload=payload,
        payload_hash=payload_hash,
        signature_valid=True,
        status="RECEIVED",
    )
    db.add(inbox)
    db.add(
        models.AuditEvent(
            actor_id="codestra",
            action="CODESTRA_RECEIPT_RECEIVED",
            resource_type="integration_message",
            resource_id=message_id,
            request_id=request.headers.get("X-Request-ID"),
            details={"event_type": event_type, "payload_hash": payload_hash},
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        duplicate = await db.scalar(
            select(IntegrationInboxMessage).where(
                IntegrationInboxMessage.provider == "codestra",
                IntegrationInboxMessage.event_id == message_id,
            )
        )
        if duplicate and duplicate.payload_hash == payload_hash:
            return {"received": True, "duplicate": True, "message_id": message_id}
        raise HTTPException(status_code=409, detail="Codestra receipt collision")
    return {"received": True, "duplicate": False, "message_id": message_id}
