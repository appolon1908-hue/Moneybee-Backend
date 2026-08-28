from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.auth import Principal, require_permission
from app.config import settings
from app.db import get_db
from app.integration_models import IntegrationInboxMessage
from app.portal.common import problem


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]


def verify_provider_signature(
    raw_body: bytes,
    signature: str | None,
    timestamp: str | None,
    secret: str | None,
    *,
    tolerance_seconds: int,
    now: int | None = None,
) -> bool:
    if not signature or not timestamp or not secret:
        return False
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp_value) > tolerance_seconds:
        return False
    signed = timestamp.encode("utf-8") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    supplied = signature.strip().removeprefix("sha256=")
    return hmac.compare_digest(expected, supplied)


def _event_id(payload: dict, header_value: str | None, payload_hash: str) -> str:
    value = (
        header_value
        or payload.get("event_id")
        or payload.get("id")
        or payload.get("webhook_id")
        or f"sha256:{payload_hash}"
    )
    return str(value)[:255]


def _event_type(payload: dict) -> str:
    return str(
        payload.get("event_type")
        or payload.get("type")
        or payload.get("event")
        or "unknown"
    )[:160]


@router.post(
    "/webhooks/providers/{provider}",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks"],
)
async def provider_webhook(
    provider: str,
    request: Request,
    db: Db,
    signature: Annotated[
        str | None, Header(alias="X-MoneyBee-Signature")
    ] = None,
    timestamp_header: Annotated[
        str | None, Header(alias="X-MoneyBee-Timestamp")
    ] = None,
    provider_event_header: Annotated[
        str | None, Header(alias="X-Provider-Event-ID")
    ] = None,
):
    """Authenticate and durably enqueue an external event without mutating lending state."""
    return await receive_provider_webhook(
        provider,
        request,
        db,
        signature=signature,
        timestamp_header=timestamp_header,
        provider_event_header=provider_event_header,
    )


async def receive_provider_webhook(
    provider: str,
    request: Request,
    db: AsyncSession,
    *,
    signature: str | None = None,
    timestamp_header: str | None = None,
    provider_event_header: str | None = None,
    metadata: dict[str, str] | None = None,
):
    provider_key = provider.strip().lower()
    if provider_key not in settings.provider_webhook_allowlist:
        raise HTTPException(status_code=404, detail="Webhook provider not found")
    secret = settings.provider_webhook_secrets.get(provider_key)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "WEBHOOK_PROVIDER_NOT_CONFIGURED",
                "provider": provider_key,
                "message": "The webhook provider is not configured.",
            },
        )
    raw_body = await request.body()
    if len(raw_body) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    if not verify_provider_signature(
        raw_body,
        signature,
        timestamp_header,
        secret,
        tolerance_seconds=settings.provider_webhook_tolerance_seconds,
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    payload_hash = hashlib.sha256(raw_body).hexdigest()
    event_id = _event_id(payload, provider_event_header, payload_hash)
    event_type = _event_type(payload)
    existing = await db.scalar(
        select(models.WebhookReceipt).where(
            models.WebhookReceipt.provider == provider_key,
            models.WebhookReceipt.provider_event_id == event_id,
        )
    )
    if existing:
        if existing.payload_hash != payload_hash:
            problem(
                "WEBHOOK_EVENT_ID_CONFLICT",
                "The provider event ID was already received with a different payload.",
                409,
            )
        return {
            "received": True,
            "duplicate": True,
            "provider": provider_key,
            "event_id": event_id,
            "receipt_id": str(existing.id),
        }

    receipt = models.WebhookReceipt(
        provider=provider_key,
        provider_event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        payload_metadata={
            "tenant_id": payload.get("tenant_id"),
            "aggregate_id": payload.get("aggregate_id")
            or payload.get("application_id")
            or payload.get("submission_id"),
            "content_type": request.headers.get("content-type"),
            **(metadata or {}),
        },
        status="RECEIVED",
    )
    inbox = IntegrationInboxMessage(
        provider=provider_key,
        event_id=event_id,
        event_type=event_type,
        tenant_id=(
            str(payload.get("tenant_id"))
            if payload.get("tenant_id") is not None
            else None
        ),
        payload=payload,
        payload_hash=payload_hash,
        signature_valid=True,
        status="RECEIVED",
    )
    db.add(receipt)
    db.add(inbox)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        duplicate = await db.scalar(
            select(models.WebhookReceipt).where(
                models.WebhookReceipt.provider == provider_key,
                models.WebhookReceipt.provider_event_id == event_id,
            )
        )
        if duplicate and duplicate.payload_hash == payload_hash:
            return {
                "received": True,
                "duplicate": True,
                "provider": provider_key,
                "event_id": event_id,
                "receipt_id": str(duplicate.id),
            }
        problem(
            "WEBHOOK_EVENT_ID_CONFLICT",
            "The provider event could not be stored safely.",
            409,
        )
    db.add(
        models.AuditEvent(
            actor_id=f"webhook:{provider_key}",
            action="PROVIDER_WEBHOOK_RECEIVED",
            resource_type="webhook_receipt",
            resource_id=str(receipt.id),
            request_id=request.headers.get("X-Request-ID"),
            details={
                "provider": provider_key,
                "event_id": event_id,
                "event_type": event_type,
                "payload_hash": payload_hash,
            },
        )
    )
    await db.commit()
    return {
        "received": True,
        "duplicate": False,
        "provider": provider_key,
        "event_id": event_id,
        "receipt_id": str(receipt.id),
    }


@router.post(
    "/webhooks/lenders/{lender_id}",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks"],
)
async def lender_webhook(
    lender_id: uuid.UUID,
    request: Request,
    db: Db,
    signature: Annotated[
        str | None, Header(alias="X-MoneyBee-Signature")
    ] = None,
    timestamp_header: Annotated[
        str | None, Header(alias="X-MoneyBee-Timestamp")
    ] = None,
    provider_event_header: Annotated[
        str | None, Header(alias="X-Provider-Event-ID")
    ] = None,
):
    response = await receive_provider_webhook(
        "lender",
        request,
        db,
        signature=signature,
        timestamp_header=timestamp_header,
        provider_event_header=provider_event_header,
        metadata={
            "endpoint_alias": "lender",
            "lender_id": str(lender_id),
        },
    )
    response["lender_id"] = str(lender_id)
    return response


@router.post(
    "/webhooks/docusign",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks"],
)
async def docusign_webhook(
    request: Request,
    db: Db,
    signature: Annotated[
        str | None, Header(alias="X-MoneyBee-Signature")
    ] = None,
    timestamp_header: Annotated[
        str | None, Header(alias="X-MoneyBee-Timestamp")
    ] = None,
    provider_event_header: Annotated[
        str | None, Header(alias="X-Provider-Event-ID")
    ] = None,
):
    return await receive_provider_webhook(
        "docusign",
        request,
        db,
        signature=signature,
        timestamp_header=timestamp_header,
        provider_event_header=provider_event_header,
        metadata={"endpoint_alias": "docusign"},
    )


@router.post(
    "/webhooks/odoo/actions",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks"],
)
async def odoo_action_webhook(
    request: Request,
    db: Db,
    signature: Annotated[
        str | None, Header(alias="X-MoneyBee-Signature")
    ] = None,
    timestamp_header: Annotated[
        str | None, Header(alias="X-MoneyBee-Timestamp")
    ] = None,
    provider_event_header: Annotated[
        str | None, Header(alias="X-Provider-Event-ID")
    ] = None,
):
    return await receive_provider_webhook(
        "odoo",
        request,
        db,
        signature=signature,
        timestamp_header=timestamp_header,
        provider_event_header=provider_event_header,
        metadata={"endpoint_alias": "odoo.actions"},
    )


@router.post(
    "/webhooks/communications/{provider}",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks"],
)
async def communication_webhook(
    provider: str,
    request: Request,
    db: Db,
    signature: Annotated[
        str | None, Header(alias="X-MoneyBee-Signature")
    ] = None,
    timestamp_header: Annotated[
        str | None, Header(alias="X-MoneyBee-Timestamp")
    ] = None,
    provider_event_header: Annotated[
        str | None, Header(alias="X-Provider-Event-ID")
    ] = None,
):
    provider_key = provider.strip().lower()
    if provider_key not in {"sendgrid", "twilio"}:
        raise HTTPException(status_code=404, detail="Webhook provider not found")
    return await receive_provider_webhook(
        provider_key,
        request,
        db,
        signature=signature,
        timestamp_header=timestamp_header,
        provider_event_header=provider_event_header,
        metadata={"endpoint_alias": f"communications.{provider_key}"},
    )


@router.post(
    "/webhooks/n8n",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks"],
)
async def n8n_webhook(
    request: Request,
    db: Db,
    signature: Annotated[
        str | None, Header(alias="X-MoneyBee-Signature")
    ] = None,
    timestamp_header: Annotated[
        str | None, Header(alias="X-MoneyBee-Timestamp")
    ] = None,
    provider_event_header: Annotated[
        str | None, Header(alias="X-Provider-Event-ID")
    ] = None,
):
    return await receive_provider_webhook(
        "n8n",
        request,
        db,
        signature=signature,
        timestamp_header=timestamp_header,
        provider_event_header=provider_event_header,
        metadata={"endpoint_alias": "n8n"},
    )


@router.post(
    "/webhooks/experian",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks"],
)
async def experian_webhook(
    request: Request,
    db: Db,
    signature: Annotated[
        str | None, Header(alias="X-MoneyBee-Signature")
    ] = None,
    timestamp_header: Annotated[
        str | None, Header(alias="X-MoneyBee-Timestamp")
    ] = None,
    provider_event_header: Annotated[
        str | None, Header(alias="X-Provider-Event-ID")
    ] = None,
):
    return await receive_provider_webhook(
        "experian",
        request,
        db,
        signature=signature,
        timestamp_header=timestamp_header,
        provider_event_header=provider_event_header,
        metadata={"endpoint_alias": "experian"},
    )


@router.get(
    "/admin/webhook-receipts",
    tags=["admin", "integrations"],
)
async def webhook_receipts(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.read"))],
    provider: Annotated[str | None, Query(max_length=100)] = None,
    receipt_status: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    statement = select(models.WebhookReceipt)
    if provider:
        statement = statement.where(models.WebhookReceipt.provider == provider.lower())
    if receipt_status:
        statement = statement.where(models.WebhookReceipt.status == receipt_status)
    rows = list(
        (
            await db.scalars(
                statement.order_by(models.WebhookReceipt.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [
        {
            "id": str(row.id),
            "provider": row.provider,
            "provider_event_id": row.provider_event_id,
            "event_type": row.event_type,
            "payload_hash": row.payload_hash,
            "payload_metadata": row.payload_metadata,
            "status": row.status,
            "processed_at": row.processed_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.get(
    "/admin/webhooks/configuration",
    tags=["admin", "integrations"],
)
async def webhook_configuration(
    user: Annotated[Principal, Depends(require_permission("capability.read"))],
):
    secrets = settings.provider_webhook_secrets
    return {
        "signature_algorithm": "HMAC-SHA256",
        "timestamp_tolerance_seconds": settings.provider_webhook_tolerance_seconds,
        "providers": [
            {"provider": provider, "configured": bool(secrets.get(provider))}
            for provider in sorted(settings.provider_webhook_allowlist)
        ],
    }


@router.post(
    "/admin/webhook-receipts/{receipt_id}/requeue",
    tags=["admin", "integrations"],
)
async def requeue_webhook_receipt(
    receipt_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.manage"))],
):
    receipt = await db.scalar(
        select(models.WebhookReceipt)
        .where(models.WebhookReceipt.id == receipt_id)
        .with_for_update()
    )
    if receipt is None:
        raise HTTPException(status_code=404, detail="Webhook receipt not found")
    inbox = await db.scalar(
        select(IntegrationInboxMessage).where(
            IntegrationInboxMessage.provider == receipt.provider,
            IntegrationInboxMessage.event_id == receipt.provider_event_id,
        )
    )
    if inbox is None:
        problem(
            "WEBHOOK_INBOX_MISSING",
            "The durable inbox record is missing; requeue is unsafe.",
            409,
        )
    if inbox.status == "PROCESSING":
        problem(
            "WEBHOOK_ALREADY_PROCESSING",
            "The webhook is currently being processed.",
            409,
        )
    receipt.status = "RETRY"
    receipt.processed_at = None
    inbox.status = "RECEIVED"
    inbox.processed_at = None
    inbox.last_error = None
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="PROVIDER_WEBHOOK_REQUEUED",
            resource_type="webhook_receipt",
            resource_id=str(receipt.id),
            details={
                "provider": receipt.provider,
                "event_id": receipt.provider_event_id,
                "inbox_id": str(inbox.id),
            },
        )
    )
    await db.commit()
    return {
        "id": str(receipt.id),
        "status": receipt.status,
        "inbox_status": inbox.status,
    }
