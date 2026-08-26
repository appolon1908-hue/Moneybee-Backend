from __future__ import annotations

import hashlib
import hmac
import importlib
import inspect
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Principal, get_current_user
from app.config import settings
from app.db import get_db
from app.portal_models import ProviderWebhookReceipt
from app.portal_permissions import require_active_organization, require_any_permission

router = APIRouter(tags=["provider-webhooks"])

MAX_WEBHOOK_BYTES = 2 * 1024 * 1024
MAX_DELIVERY_ATTEMPTS = 12
REPLAY_WINDOW_SECONDS = 300
SUPPORTED_PROVIDERS = frozenset(
    {
        "banking",
        "codestra",
        "docusign",
        "esign",
        "experian",
        "lender",
        "middesk",
        "n8n",
        "odoo",
        "plaid",
    }
)
PROVIDER_ADAPTERS = {
    "plaid": ("app.integrations.plaid", "PlaidAdapter"),
    "middesk": ("app.integrations.middesk", "MiddeskAdapter"),
    "experian": ("app.integrations.experian", "ExperianAdapter"),
}


class WebhookVerificationUnavailable(RuntimeError):
    pass


class WebhookSignatureInvalid(RuntimeError):
    pass


def _normalized_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{2,40}", normalized):
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_PROVIDER", "message": "Provider is not supported."},
        )
    if normalized not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_PROVIDER", "message": "Provider is not supported."},
        )
    return normalized


def _header(headers: Mapping[str, str], *names: str) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return value.strip()
    return None


def _provider_secret(provider: str) -> str:
    name = f"MONEYBEE_WEBHOOK_SECRET_{provider.upper().replace('-', '_')}"
    secret = os.getenv(name, "").strip()
    if not secret:
        raise WebhookVerificationUnavailable(
            f"Webhook verification is not configured for {provider}"
        )
    return secret


def _parse_timestamp(raw_value: str | None) -> int:
    if not raw_value:
        raise WebhookSignatureInvalid("Webhook timestamp is missing")
    try:
        return int(raw_value)
    except ValueError as exc:
        raise WebhookSignatureInvalid("Webhook timestamp is invalid") from exc


def _generic_signature(
    *,
    secret: str,
    timestamp: int,
    body: bytes,
) -> str:
    signed = str(timestamp).encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def verify_generic_hmac(
    *,
    provider: str,
    body: bytes,
    headers: Mapping[str, str],
    now: datetime | None = None,
) -> None:
    timestamp = _parse_timestamp(
        _header(headers, "X-MoneyBee-Timestamp", "X-Webhook-Timestamp")
    )
    current = int((now or datetime.now(UTC)).timestamp())
    if abs(current - timestamp) > REPLAY_WINDOW_SECONDS:
        raise WebhookSignatureInvalid("Webhook timestamp is outside the replay window")

    received = _header(
        headers,
        "X-MoneyBee-Signature",
        "X-Webhook-Signature",
        "X-Signature",
    )
    if not received:
        raise WebhookSignatureInvalid("Webhook signature is missing")
    if received.startswith("v1="):
        received = received[3:]
    expected = _generic_signature(
        secret=_provider_secret(provider), timestamp=timestamp, body=body
    )
    if not hmac.compare_digest(expected, received.lower()):
        raise WebhookSignatureInvalid("Webhook signature is invalid")


def _adapter_signature(provider: str, headers: Mapping[str, str]) -> str | None:
    if provider == "plaid":
        return _header(headers, "Plaid-Verification")
    if provider == "middesk":
        return _header(headers, "Middesk-Signature", "X-Middesk-Signature")
    if provider == "experian":
        return _header(headers, "X-Experian-Signature", "X-Webhook-Signature")
    return None


def _instantiate_adapter(module_name: str, class_name: str):
    module = importlib.import_module(module_name)
    adapter_class = getattr(module, class_name)
    for args in ((), (settings,)):
        try:
            return adapter_class(*args)
        except TypeError:
            continue
    raise WebhookVerificationUnavailable(
        f"The {class_name} webhook verifier could not be initialized"
    )


async def verify_provider_webhook(
    *,
    provider: str,
    body: bytes,
    headers: Mapping[str, str],
) -> None:
    adapter_spec = PROVIDER_ADAPTERS.get(provider)
    signature = _adapter_signature(provider, headers)
    if adapter_spec is None or not signature:
        verify_generic_hmac(provider=provider, body=body, headers=headers)
        return

    try:
        adapter = _instantiate_adapter(*adapter_spec)
        verifier = getattr(adapter, "verify_webhook", None)
        if verifier is None:
            verify_generic_hmac(provider=provider, body=body, headers=headers)
            return
        result = verifier(body, signature)
        if inspect.isawaitable(result):
            result = await result
    except WebhookVerificationUnavailable:
        raise
    except Exception as exc:
        raise WebhookSignatureInvalid("Provider webhook verification failed") from exc
    if result is not True:
        raise WebhookSignatureInvalid("Provider webhook signature is invalid")


def _payload_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _event_id(
    *,
    payload: dict[str, Any],
    headers: Mapping[str, str],
    payload_hash: str,
) -> str:
    header_value = _header(
        headers,
        "X-Provider-Event-Id",
        "X-Webhook-Id",
        "X-Request-Id",
        "Plaid-Request-Id",
    )
    if header_value:
        return header_value[:255]
    for key in ("event_id", "eventId", "webhook_id", "webhookId", "id"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()[:255]
    return payload_hash


def _event_type(payload: dict[str, Any], headers: Mapping[str, str]) -> str:
    header_value = _header(headers, "X-Event-Type", "X-Webhook-Event")
    if header_value:
        return header_value[:160]
    for key in ("event_type", "eventType", "type", "webhook_code", "webhook_type"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()[:160]
    return "UNKNOWN"


def _tenant_id(payload: dict[str, Any], headers: Mapping[str, str]) -> str | None:
    header_value = _header(headers, "X-Tenant-Id", "X-Organization-Id")
    if header_value:
        return header_value[:160]
    for key in ("tenant_id", "tenantId", "organization_id", "organizationId"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()[:160]
    return None


def _receipt_read(receipt: ProviderWebhookReceipt, *, include_payload: bool = False):
    result = {
        "id": str(receipt.id),
        "provider": receipt.provider,
        "provider_event_id": receipt.provider_event_id,
        "event_type": receipt.event_type,
        "tenant_id": receipt.tenant_id,
        "payload_hash": receipt.payload_hash,
        "signature_valid": receipt.signature_valid,
        "status": receipt.status,
        "attempts": receipt.attempts,
        "next_attempt_at": receipt.next_attempt_at,
        "processed_at": receipt.processed_at,
        "last_error": receipt.last_error,
        "metadata": receipt.metadata_payload,
        "created_at": receipt.created_at,
        "updated_at": receipt.updated_at,
    }
    if include_payload:
        result["payload"] = receipt.payload
    return result


def retry_delay(attempt: int) -> timedelta:
    bounded = max(1, min(attempt, 10))
    return timedelta(seconds=min(3600, 2 ** bounded * 15))


def claim_provider_webhooks(
    db: Session,
    *,
    worker_id: str,
    limit: int = 50,
    lease_seconds: int = 120,
) -> list[ProviderWebhookReceipt]:
    now = datetime.now(UTC)
    statement = (
        select(ProviderWebhookReceipt)
        .where(
            or_(
                ProviderWebhookReceipt.status.in_(("RECEIVED", "RETRY")),
                (
                    (ProviderWebhookReceipt.status == "PROCESSING")
                    & (ProviderWebhookReceipt.next_attempt_at <= now)
                ),
            ),
            or_(
                ProviderWebhookReceipt.next_attempt_at.is_(None),
                ProviderWebhookReceipt.next_attempt_at <= now,
            ),
            ProviderWebhookReceipt.attempts < MAX_DELIVERY_ATTEMPTS,
        )
        .order_by(ProviderWebhookReceipt.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    receipts = list(db.scalars(statement))
    for receipt in receipts:
        receipt.status = "PROCESSING"
        receipt.attempts += 1
        receipt.next_attempt_at = now + timedelta(seconds=lease_seconds)
        receipt.metadata_payload = {
            **(receipt.metadata_payload or {}),
            "lease_owner": worker_id,
            "lease_acquired_at": now.isoformat(),
        }
    db.commit()
    return receipts


def complete_provider_webhook(
    db: Session,
    receipt: ProviderWebhookReceipt,
) -> None:
    receipt.status = "PROCESSED"
    receipt.processed_at = datetime.now(UTC)
    receipt.next_attempt_at = None
    receipt.last_error = None
    db.commit()


def fail_provider_webhook(
    db: Session,
    receipt: ProviderWebhookReceipt,
    *,
    error: str,
) -> None:
    receipt.last_error = error[:4000]
    if receipt.attempts >= MAX_DELIVERY_ATTEMPTS:
        receipt.status = "DEAD_LETTER"
        receipt.next_attempt_at = None
    else:
        receipt.status = "RETRY"
        receipt.next_attempt_at = datetime.now(UTC) + retry_delay(receipt.attempts)
    db.commit()


@router.post(
    "/webhooks/providers/{provider}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_provider_webhook(
    provider: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    normalized_provider = _normalized_provider(provider)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/json":
        raise HTTPException(
            status_code=415,
            detail={"code": "JSON_REQUIRED", "message": "Webhook body must be JSON."},
        )
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "WEBHOOK_TOO_LARGE", "message": "Webhook is too large."},
        )
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "WEBHOOK_TOO_LARGE", "message": "Webhook is too large."},
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_JSON", "message": "Webhook JSON is invalid."},
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_ENVELOPE", "message": "Webhook must be an object."},
        )

    try:
        await verify_provider_webhook(
            provider=normalized_provider,
            body=body,
            headers=request.headers,
        )
    except WebhookVerificationUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "WEBHOOK_VERIFICATION_UNAVAILABLE",
                "message": "Webhook verification is not configured.",
            },
        ) from exc
    except WebhookSignatureInvalid as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_WEBHOOK_SIGNATURE", "message": str(exc)},
        ) from exc

    digest = _payload_hash(body)
    provider_event_id = _event_id(
        payload=payload, headers=request.headers, payload_hash=digest
    )
    existing = db.scalar(
        select(ProviderWebhookReceipt).where(
            ProviderWebhookReceipt.provider == normalized_provider,
            ProviderWebhookReceipt.provider_event_id == provider_event_id,
        )
    )
    if existing is not None:
        if existing.payload_hash != digest:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROVIDER_EVENT_CONFLICT",
                    "message": "The provider event ID was reused with another payload.",
                },
            )
        return {
            "receipt_id": str(existing.id),
            "status": existing.status,
            "duplicate": True,
        }

    receipt = ProviderWebhookReceipt(
        provider=normalized_provider,
        provider_event_id=provider_event_id,
        event_type=_event_type(payload, request.headers),
        tenant_id=_tenant_id(payload, request.headers),
        payload_hash=digest,
        payload=payload,
        signature_valid=True,
        status="RECEIVED",
        attempts=0,
        next_attempt_at=datetime.now(UTC),
        metadata_payload={
            "correlation_id": _header(
                request.headers, "X-Correlation-Id", "X-Request-Id"
            ),
            "content_type": content_type,
        },
    )
    db.add(receipt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(ProviderWebhookReceipt).where(
                ProviderWebhookReceipt.provider == normalized_provider,
                ProviderWebhookReceipt.provider_event_id == provider_event_id,
            )
        )
        if concurrent is None or concurrent.payload_hash != digest:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROVIDER_EVENT_CONFLICT",
                    "message": "The provider event could not be deduplicated.",
                },
            )
        return {
            "receipt_id": str(concurrent.id),
            "status": concurrent.status,
            "duplicate": True,
        }
    db.refresh(receipt)
    return {
        "receipt_id": str(receipt.id),
        "status": receipt.status,
        "duplicate": False,
    }


@router.get("/admin/webhook-receipts")
def list_webhook_receipts(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    provider: str | None = Query(default=None, max_length=40),
    receipt_status: str | None = Query(default=None, alias="status", max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
):
    if "MONEYBEE" not in principal.membership_types:
        raise HTTPException(status_code=403, detail={"code": "MONEYBEE_CONTEXT_REQUIRED"})
    require_active_organization(principal)
    require_any_permission(principal, "capability.read", "*")
    statement = select(ProviderWebhookReceipt)
    if provider:
        statement = statement.where(
            ProviderWebhookReceipt.provider == _normalized_provider(provider)
        )
    if receipt_status:
        statement = statement.where(
            ProviderWebhookReceipt.status == receipt_status.upper()
        )
    receipts = db.scalars(
        statement.order_by(ProviderWebhookReceipt.created_at.desc()).limit(limit)
    )
    return {"items": [_receipt_read(item) for item in receipts]}


@router.get("/admin/webhook-receipts/{receipt_id}")
def get_webhook_receipt(
    receipt_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_payload: bool = Query(default=False),
):
    if "MONEYBEE" not in principal.membership_types:
        raise HTTPException(status_code=403, detail={"code": "MONEYBEE_CONTEXT_REQUIRED"})
    require_active_organization(principal)
    require_any_permission(principal, "capability.read", "*")
    if include_payload:
        require_any_permission(principal, "capability.manage", "*")
    receipt = db.get(ProviderWebhookReceipt, receipt_id)
    if receipt is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Webhook receipt was not found."},
        )
    return _receipt_read(receipt, include_payload=include_payload)


@router.post("/admin/webhook-receipts/{receipt_id}/requeue")
def requeue_webhook_receipt(
    receipt_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if "MONEYBEE" not in principal.membership_types:
        raise HTTPException(status_code=403, detail={"code": "MONEYBEE_CONTEXT_REQUIRED"})
    require_active_organization(principal)
    require_any_permission(principal, "capability.manage", "*")
    receipt = db.get(ProviderWebhookReceipt, receipt_id)
    if receipt is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Webhook receipt was not found."},
        )
    if receipt.status not in {"FAILED", "RETRY", "DEAD_LETTER"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REQUEUE_NOT_ALLOWED",
                "message": "Only failed or dead-letter receipts can be requeued.",
            },
        )
    if receipt.attempts >= MAX_DELIVERY_ATTEMPTS:
        receipt.attempts = 0
    receipt.status = "RECEIVED"
    receipt.next_attempt_at = datetime.now(UTC)
    receipt.processed_at = None
    receipt.last_error = None
    receipt.metadata_payload = {
        **(receipt.metadata_payload or {}),
        "manually_requeued_by": str(principal.user_id),
        "manually_requeued_at": datetime.now(UTC).isoformat(),
    }
    db.commit()
    db.refresh(receipt)
    return _receipt_read(receipt)
