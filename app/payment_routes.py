from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated, Any

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
_LINKAGE_KEYS = frozenset(
    {
        "application_id",
        "funding_id",
        "payout_id",
        "commission_id",
        "moneybee_application_id",
        "moneybee_funding_id",
        "moneybee_payout_id",
        "moneybee_commission_id",
    }
)


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value[:500]
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _minimized_payment_payload(
    provider: str,
    *,
    event_id: str,
    event_type: str,
    payload: dict,
) -> dict:
    """Keep operational correlation fields, never the provider's full payload.

    Card, bank, payer, customer, billing, shipping, email, phone, and free-form
    provider metadata are deliberately excluded. The full signed bytes are used
    only to calculate `payload_hash` and are not persisted.
    """
    if provider == "stripe":
        provider_object = _mapping(_mapping(payload.get("data")).get("object"))
        amount_value = provider_object.get("amount")
        if amount_value is None:
            amount_value = provider_object.get("amount_received")
        currency = provider_object.get("currency")
        created = payload.get("created")
        live_mode = payload.get("livemode")
    else:
        provider_object = _mapping(payload.get("resource"))
        amount = _mapping(provider_object.get("amount"))
        amount_value = amount.get("value") or amount.get("total")
        currency = amount.get("currency_code") or amount.get("currency")
        created = payload.get("create_time")
        live_mode = None

    metadata = _mapping(provider_object.get("metadata"))
    linkage = {
        key: safe
        for key in _LINKAGE_KEYS
        if (safe := _safe_scalar(metadata.get(key))) is not None
    }
    object_fields = {
        "id": _safe_scalar(provider_object.get("id")),
        "type": _safe_scalar(
            provider_object.get("object") or provider_object.get("resource_type")
        ),
        "status": _safe_scalar(provider_object.get("status")),
        "amount": _safe_scalar(amount_value),
        "currency": _safe_scalar(currency),
        "reference_id": _safe_scalar(
            provider_object.get("reference_id")
            or provider_object.get("invoice_id")
            or provider_object.get("transfer_group")
        ),
    }
    minimized = {
        "provider": provider,
        "event_id": event_id,
        "event_type": event_type,
        "object": {key: value for key, value in object_fields.items() if value is not None},
        "linkage": linkage,
        "created": _safe_scalar(created),
    }
    if isinstance(live_mode, bool):
        minimized["livemode"] = live_mode
    return minimized


def _duplicate_receipt(existing: models.WebhookReceipt, payload_hash: str) -> dict:
    if not hmac.compare_digest(existing.payload_hash, payload_hash):
        problem(
            "WEBHOOK_EVENT_ID_CONFLICT",
            "This payment event ID was already received with different signed content.",
            409,
        )
    return {"received": True, "duplicate": True, "receipt_id": str(existing.id)}


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
        return _duplicate_receipt(existing, payload_hash)

    receipt = models.WebhookReceipt(
        provider=provider,
        provider_event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        payload_metadata={
            "content_type": request.headers.get("content-type"),
            "payload_storage": "minimized",
            "raw_payload_stored": False,
            "retention_class": "payment_webhook_receipt",
        },
        status="RECEIVED",
    )
    inbox = IntegrationInboxMessage(
        provider=provider,
        event_id=event_id,
        event_type=event_type,
        payload=_minimized_payment_payload(
            provider,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
        ),
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
            return _duplicate_receipt(duplicate, payload_hash)
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
        "stripe",
        request,
        db,
        raw_body=raw_body,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
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
        "paypal",
        request,
        db,
        raw_body=raw_body,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
