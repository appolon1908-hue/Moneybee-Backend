from __future__ import annotations

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_db
from app.integration_models import IntegrationInboxMessage
from app.integrations.payments import PayPalAdapter, StripeAdapter
from app.portal.common import problem


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]


async def _land_payment_webhook(
    provider: str,
    request: Request,
    db: AsyncSession,
    *,
    raw_body: bytes,
    event_id: str,
    event_type: str,
    payload: dict,
) -> dict:
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    existing = await db.scalar(
        select(models.WebhookReceipt).where(
            models.WebhookReceipt.provider == provider,
            models.WebhookReceipt.provider_event_id == event_id,
        )
    )
    if existing is not None:
        return {"received": True, "duplicate": True, "receipt_id": str(existing.id)}

    receipt = models.WebhookReceipt(
        provider=provider,
        provider_event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        payload_metadata={"content_type": request.headers.get("content-type")},
        status="RECEIVED",
    )
    inbox = IntegrationInboxMessage(
        provider=provider,
        event_id=event_id,
        event_type=event_type,
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
                models.WebhookReceipt.provider == provider,
                models.WebhookReceipt.provider_event_id == event_id,
            )
        )
        if duplicate is not None:
            return {"received": True, "duplicate": True, "receipt_id": str(duplicate.id)}
        problem("WEBHOOK_EVENT_ID_CONFLICT", "The payment event could not be stored safely.", 409)
    db.add(
        models.AuditEvent(
            actor_id=f"webhook:{provider}",
            action="PAYMENT_WEBHOOK_RECEIVED",
            resource_type="webhook_receipt",
            resource_id=str(receipt.id),
            request_id=request.headers.get("X-Request-ID"),
            details={"provider": provider, "event_id": event_id, "event_type": event_type},
        )
    )
    await db.commit()
    return {"received": True, "duplicate": False, "receipt_id": str(receipt.id)}


@router.post(
    "/webhooks/stripe",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks", "payments"],
)
async def stripe_webhook(
    request: Request,
    db: Db,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
):
    raw_body = await request.body()
    if len(raw_body) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    if not StripeAdapter().verify_webhook(raw_body, stripe_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    event_id = str(payload.get("id") or f"sha256:{hashlib.sha256(raw_body).hexdigest()}")
    event_type = str(payload.get("type") or "unknown")
    return await _land_payment_webhook(
        "stripe", request, db, raw_body=raw_body, event_id=event_id, event_type=event_type, payload=payload
    )


@router.post(
    "/webhooks/paypal",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["provider-webhooks", "payments"],
)
async def paypal_webhook(request: Request, db: Db):
    raw_body = await request.body()
    if len(raw_body) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    header_map = {key.lower(): value for key, value in request.headers.items()}
    if not await PayPalAdapter().verify_webhook(raw_body, header_map):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    event_id = str(payload.get("id") or f"sha256:{hashlib.sha256(raw_body).hexdigest()}")
    event_type = str(payload.get("event_type") or "unknown")
    return await _land_payment_webhook(
        "paypal", request, db, raw_body=raw_body, event_id=event_id, event_type=event_type, payload=payload
    )
