import hashlib
import hmac
import json
import os
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import identity_models, models
from app.auth import User, get_current_user
from app.db import get_db
from app.integration_models import IntegrationInboxMessage
from app.portal_security import require_moneybee_admin

router = APIRouter(tags=["provider-webhook-gateway"])

PROVIDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _construct(model: type, values: dict[str, Any]) -> Any:
    columns = {column.name for column in model.__table__.columns}
    return model(**{key: value for key, value in values.items() if key in columns})


def _configured_secrets(provider: str) -> tuple[str, ...]:
    normalized = provider.upper().replace("-", "_")
    direct = os.getenv(f"MONEYBEE_WEBHOOK_SECRET_{normalized}", "").strip()
    configured: list[str] = [direct] if direct else []
    raw_json = os.getenv("MONEYBEE_WEBHOOK_SECRETS_JSON", "").strip()
    if raw_json:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise _problem(
                "WEBHOOK_SECRET_CONFIGURATION_INVALID",
                "Webhook secret configuration is not valid JSON.",
                503,
            ) from exc
        values = payload.get(provider) if isinstance(payload, dict) else None
        if isinstance(values, str):
            configured.append(values)
        elif isinstance(values, list):
            configured.extend(str(value) for value in values if str(value).strip())
    secrets = tuple(dict.fromkeys(secret for secret in configured if secret))
    if not secrets:
        raise _problem(
            "WEBHOOK_PROVIDER_NOT_CONFIGURED",
            "This webhook provider is not configured.",
            404,
        )
    return secrets


def _timestamp(value: str | None, now: int | None = None) -> int:
    if not value:
        raise _problem(
            "WEBHOOK_TIMESTAMP_REQUIRED",
            "X-MoneyBee-Timestamp is required.",
            400,
        )
    try:
        timestamp = int(value)
    except ValueError as exc:
        raise _problem(
            "WEBHOOK_TIMESTAMP_INVALID",
            "Webhook timestamp must be Unix epoch seconds.",
            400,
        ) from exc
    tolerance = int(os.getenv("MONEYBEE_WEBHOOK_TOLERANCE_SECONDS", "300"))
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance:
        raise _problem(
            "WEBHOOK_TIMESTAMP_OUTSIDE_TOLERANCE",
            "Webhook timestamp is outside the accepted replay window.",
            401,
        )
    return timestamp


def _signature_digest(
    *,
    secret: str,
    timestamp: int,
    event_id: str,
    body: bytes,
) -> str:
    signed = str(timestamp).encode("ascii") + b"." + event_id.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def _verify_signature(
    *,
    provider: str,
    timestamp: int,
    event_id: str,
    body: bytes,
    supplied_signature: str | None,
) -> None:
    if not supplied_signature:
        raise _problem(
            "WEBHOOK_SIGNATURE_REQUIRED",
            "X-MoneyBee-Signature is required.",
            401,
        )
    supplied = supplied_signature.strip()
    if supplied.startswith("v1="):
        supplied = supplied[3:]
    if not re.fullmatch(r"[a-fA-F0-9]{64}", supplied):
        raise _problem(
            "WEBHOOK_SIGNATURE_INVALID",
            "Webhook signature has an invalid format.",
            401,
        )
    for secret in _configured_secrets(provider):
        expected = _signature_digest(
            secret=secret,
            timestamp=timestamp,
            event_id=event_id,
            body=body,
        )
        if hmac.compare_digest(expected, supplied.lower()):
            return
    raise _problem(
        "WEBHOOK_SIGNATURE_INVALID",
        "Webhook signature verification failed.",
        401,
    )


def _receipt_public(receipt: IntegrationInboxMessage) -> dict[str, Any]:
    return {
        "id": str(receipt.id),
        "provider": receipt.provider,
        "event_id": receipt.event_id,
        "event_type": receipt.event_type,
        "tenant_id": str(receipt.tenant_id) if receipt.tenant_id else None,
        "payload_hash": receipt.payload_hash,
        "signature_valid": receipt.signature_valid,
        "status": receipt.status,
        "attempts": receipt.attempts,
        "last_error": receipt.last_error,
        "processed_at": receipt.processed_at,
        "created_at": receipt.created_at,
    }


@router.post("/webhooks/gateway/{provider}", status_code=202)
async def receive_provider_webhook(
    request: Request,
    provider: str = Path(pattern=r"^[a-z0-9][a-z0-9_-]{1,62}$"),
    event_id: str | None = Header(default=None, alias="X-MoneyBee-Event-ID"),
    event_type: str | None = Header(default=None, alias="X-MoneyBee-Event-Type"),
    timestamp_header: str | None = Header(default=None, alias="X-MoneyBee-Timestamp"),
    signature: str | None = Header(default=None, alias="X-MoneyBee-Signature"),
    organization_id: uuid.UUID | None = Header(default=None, alias="X-Organization-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = provider.lower()
    if not PROVIDER_PATTERN.fullmatch(provider):
        raise _problem("WEBHOOK_PROVIDER_INVALID", "Webhook provider is invalid.", 400)
    if not event_id or len(event_id) > 255:
        raise _problem(
            "WEBHOOK_EVENT_ID_REQUIRED",
            "X-MoneyBee-Event-ID is required and must be at most 255 characters.",
            400,
        )
    if not event_type or len(event_type) > 255:
        raise _problem(
            "WEBHOOK_EVENT_TYPE_REQUIRED",
            "X-MoneyBee-Event-Type is required and must be at most 255 characters.",
            400,
        )
    body = await request.body()
    max_body = int(os.getenv("MONEYBEE_WEBHOOK_MAX_BYTES", "1048576"))
    if len(body) > max_body:
        raise _problem(
            "WEBHOOK_PAYLOAD_TOO_LARGE",
            "Webhook payload exceeds the configured maximum size.",
            413,
        )
    timestamp = _timestamp(timestamp_header)
    _verify_signature(
        provider=provider,
        timestamp=timestamp,
        event_id=event_id,
        body=body,
        supplied_signature=signature,
    )
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _problem(
            "WEBHOOK_PAYLOAD_INVALID",
            "Webhook payload must be valid UTF-8 JSON.",
            400,
        ) from exc
    if organization_id is not None:
        organization = await db.get(identity_models.Organization, organization_id)
        if organization is None or not bool(getattr(organization, "active", True)):
            raise _problem(
                "WEBHOOK_ORGANIZATION_INVALID",
                "Webhook organization is not active or does not exist.",
                422,
            )
    payload_hash = hashlib.sha256(body).hexdigest()
    existing_result = await db.execute(
        select(IntegrationInboxMessage).where(
            IntegrationInboxMessage.provider == provider,
            IntegrationInboxMessage.event_id == event_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise _problem(
                "WEBHOOK_EVENT_ID_COLLISION",
                "The provider event ID was previously received with a different payload.",
                409,
            )
        return {
            "accepted": True,
            "duplicate": True,
            "receipt": _receipt_public(existing),
        }
    receipt = IntegrationInboxMessage(
        provider=provider,
        event_id=event_id,
        event_type=event_type,
        tenant_id=organization_id,
        payload=payload,
        payload_hash=payload_hash,
        signature_valid=True,
        status="RECEIVED",
        attempts=0,
    )
    db.add(receipt)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raced_result = await db.execute(
            select(IntegrationInboxMessage).where(
                IntegrationInboxMessage.provider == provider,
                IntegrationInboxMessage.event_id == event_id,
            )
        )
        raced = raced_result.scalar_one_or_none()
        if raced is None or raced.payload_hash != payload_hash:
            raise _problem(
                "WEBHOOK_EVENT_ID_COLLISION",
                "The provider event ID was received concurrently with another payload.",
                409,
            )
        return {
            "accepted": True,
            "duplicate": True,
            "receipt": _receipt_public(raced),
        }
    db.add(
        _construct(
            models.OutboxEvent,
            {
                "event_type": "ProviderWebhookReceived",
                "aggregate_type": "integration_inbox_message",
                "aggregate_id": receipt.id,
                "payload": {
                    "receipt_id": str(receipt.id),
                    "provider": provider,
                    "event_id": event_id,
                    "event_type": event_type,
                    "tenant_id": str(organization_id) if organization_id else None,
                    "payload_hash": payload_hash,
                },
                "status": "PENDING",
            },
        )
    )
    db.add(
        _construct(
            models.AuditEvent,
            {
                "actor_subject": f"webhook:{provider}",
                "action": "provider_webhook.received",
                "entity_type": "integration_inbox_message",
                "entity_id": receipt.id,
                "details": {
                    "provider": provider,
                    "event_id": event_id,
                    "event_type": event_type,
                    "payload_hash": payload_hash,
                    "timestamp": timestamp,
                    "organization_id": str(organization_id) if organization_id else None,
                },
            },
        )
    )
    await db.commit()
    await db.refresh(receipt)
    return {
        "accepted": True,
        "duplicate": False,
        "receipt": _receipt_public(receipt),
    }


@router.get("/admin/webhook-gateway/receipts")
async def list_webhook_receipts(
    provider: str | None = None,
    status: str | None = None,
    event_type: str | None = None,
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    require_moneybee_admin(user.principal)
    query = select(IntegrationInboxMessage)
    if provider:
        query = query.where(IntegrationInboxMessage.provider == provider.lower())
    if status:
        query = query.where(IntegrationInboxMessage.status == status.upper())
    if event_type:
        query = query.where(IntegrationInboxMessage.event_type == event_type)
    if before:
        query = query.where(IntegrationInboxMessage.created_at < before)
    result = await db.execute(
        query.order_by(IntegrationInboxMessage.created_at.desc()).limit(limit)
    )
    return [_receipt_public(receipt) for receipt in result.scalars().all()]


@router.get("/admin/webhook-gateway/receipts/{receipt_id}")
async def get_webhook_receipt(
    receipt_id: uuid.UUID,
    include_payload: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    require_moneybee_admin(user.principal)
    receipt = await db.get(IntegrationInboxMessage, receipt_id)
    if receipt is None:
        raise _problem(
            "WEBHOOK_RECEIPT_NOT_FOUND",
            "Webhook receipt was not found.",
            404,
        )
    response = _receipt_public(receipt)
    if include_payload:
        response["payload"] = receipt.payload
    return response


@router.post("/admin/webhook-gateway/receipts/{receipt_id}/requeue")
async def requeue_webhook_receipt(
    receipt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    require_moneybee_admin(user.principal)
    result = await db.execute(
        select(IntegrationInboxMessage)
        .where(IntegrationInboxMessage.id == receipt_id)
        .with_for_update()
    )
    receipt = result.scalar_one_or_none()
    if receipt is None:
        raise _problem(
            "WEBHOOK_RECEIPT_NOT_FOUND",
            "Webhook receipt was not found.",
            404,
        )
    if receipt.status not in {"FAILED", "DEAD", "RETRY", "BLOCKED"}:
        raise _problem(
            "WEBHOOK_RECEIPT_NOT_REQUEUEABLE",
            "Only failed or blocked webhook receipts can be requeued.",
            409,
        )
    previous_status = receipt.status
    receipt.status = "RECEIVED"
    receipt.attempts = 0
    receipt.last_error = None
    receipt.processed_at = None
    db.add(
        _construct(
            models.AuditEvent,
            {
                "actor_subject": user.principal.subject,
                "action": "provider_webhook.requeued",
                "entity_type": "integration_inbox_message",
                "entity_id": receipt.id,
                "details": {
                    "provider": receipt.provider,
                    "event_id": receipt.event_id,
                    "previous_status": previous_status,
                    "status": receipt.status,
                    "requeued_at": datetime.now(UTC).isoformat(),
                },
            },
        )
    )
    await db.commit()
    await db.refresh(receipt)
    return {
        "requeued": True,
        "receipt": _receipt_public(receipt),
    }
