import hashlib
import hmac
import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.auth import Principal, require_permission
from app.config import settings
from app.db import get_db
from app.integration_models import IntegrationInboxMessage
from app.integrations.registry import provider_statuses
from app.integrations.middesk import MiddeskAdapter


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]


def verify_codestra_signature(
    raw_body: bytes,
    signature: str | None,
    secret: str | None,
    timestamp: str | None,
    *,
    now: int | None = None,
) -> bool:
    if not signature or not secret or not timestamp:
        return False
    try:
        timestamp_value = int(timestamp)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp_value) > settings.codestra_middleware_webhook_tolerance_seconds:
        return False
    signed_payload = timestamp.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    supplied = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, supplied)


@router.post("/webhooks/codestra", tags=["provider-webhooks"], status_code=202)
async def codestra_webhook(
    request: Request,
    db: Db,
    signature: Annotated[str | None, Header(alias="X-Codestra-Signature")] = None,
    timestamp: Annotated[str | None, Header(alias="X-Codestra-Timestamp")] = None,
    message_header: Annotated[
        str | None, Header(alias="X-Codestra-Message-Id")
    ] = None,
):
    """Persist an authenticated callback without directly mutating lending state."""
    body = await request.body()
    if settings.middleware_provider != "codestra":
        raise HTTPException(status_code=503, detail="Codestra middleware is disabled")
    if not verify_codestra_signature(
        body,
        signature,
        settings.codestra_middleware_webhook_secret,
        timestamp,
    ):
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
        or payload.get("event_id")
        or f"sha256:{payload_hash}"
    )
    existing = await db.scalar(
        select(IntegrationInboxMessage).where(
            IntegrationInboxMessage.provider == "codestra",
            IntegrationInboxMessage.event_id == message_id,
        )
    )
    if existing is not None:
        return {"received": True, "duplicate": True, "message_id": message_id}

    event_type = str(payload.get("event_type") or payload.get("type") or "unknown")
    db.add(
        IntegrationInboxMessage(
            provider="codestra",
            event_id=message_id,
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
    )
    db.add(
        models.AuditEvent(
            actor_id="codestra",
            action="INTEGRATION_MESSAGE_RECEIVED",
            resource_type="integration_message",
            resource_id=message_id,
            request_id=request.headers.get("X-Request-ID"),
            details={"event_type": event_type, "payload_hash": payload_hash},
        )
    )
    await db.commit()
    return {"received": True, "duplicate": False, "message_id": message_id}


@router.post("/webhooks/middesk", tags=["provider-webhooks"], status_code=202)
async def middesk_webhook(
    request: Request,
    db: Db,
    signature: Annotated[
        str | None, Header(alias="X-Middesk-Signature-256")
    ] = None,
):
    body = await request.body()
    adapter = MiddeskAdapter()
    if not adapter.verify_webhook(body, signature):
        raise HTTPException(status_code=401, detail="Invalid Middesk signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    payload_hash = hashlib.sha256(body).hexdigest()
    event_id = str(payload.get("id") or f"sha256:{payload_hash}")
    existing = await db.scalar(
        select(IntegrationInboxMessage).where(
            IntegrationInboxMessage.provider == "middesk",
            IntegrationInboxMessage.event_id == event_id,
        )
    )
    if existing is not None:
        return {"received": True, "duplicate": True, "message_id": event_id}

    event_type = str(payload.get("type") or "unknown")
    data_object = (payload.get("data") or {}).get("object") or {}
    db.add(
        IntegrationInboxMessage(
            provider="middesk",
            event_id=event_id,
            event_type=event_type,
            tenant_id=None,
            payload=payload,
            payload_hash=payload_hash,
            signature_valid=True,
            status="RECEIVED",
        )
    )
    db.add(
        models.AuditEvent(
            actor_id="middesk",
            action="INTEGRATION_MESSAGE_RECEIVED",
            resource_type="business_verification",
            resource_id=str(data_object.get("id") or event_id),
            request_id=request.headers.get("X-Request-ID"),
            details={"event_type": event_type, "payload_hash": payload_hash},
        )
    )
    await db.commit()
    return {"received": True, "duplicate": False, "message_id": event_id}


@router.get("/admin/integration-inbox", tags=["admin", "integrations"])
async def integration_inbox(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.read"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    provider: Annotated[str | None, Query(max_length=100)] = None,
):
    statement = select(IntegrationInboxMessage)
    if provider:
        statement = statement.where(IntegrationInboxMessage.provider == provider)
    rows = (
        await db.scalars(
            statement.order_by(IntegrationInboxMessage.created_at.desc()).limit(limit)
        )
    ).all()
    return [
        {
            "id": row.id,
            "message_id": row.event_id,
            "event_type": row.event_type,
            "tenant_id": row.tenant_id,
            "status": row.status,
            "payload_hash": row.payload_hash,
            "signature_valid": row.signature_valid,
            "attempts": row.attempts,
            "last_error": row.last_error,
            "source": row.payload.get("source"),
            "aggregate_id": row.payload.get("aggregate_id"),
            "received_at": row.created_at,
            "processed_at": row.processed_at,
        }
        for row in rows
    ]


@router.get("/admin/integration-control-plane", tags=["admin", "integrations"])
async def integration_control_plane(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.read"))],
):
    inbox_count = await db.scalar(
        select(func.count(IntegrationInboxMessage.id))
    )
    pending_outbox = await db.scalar(
        select(func.count(models.OutboxEvent.id)).where(
            models.OutboxEvent.status.in_(
                [models.OutboxStatus.PENDING, models.OutboxStatus.RETRY]
            )
        )
    )
    return {
        "authority": "moneybee",
        "middleware": "codestra",
        "crm_projection": "odoo",
        "inbox_messages": inbox_count or 0,
        "pending_outbox_events": pending_outbox or 0,
        "providers": [
            {
                "provider_type": row.provider_type,
                "provider": row.provider,
                "selected": row.selected,
                "configured": row.configured,
            }
            for row in provider_statuses()
        ],
    }
