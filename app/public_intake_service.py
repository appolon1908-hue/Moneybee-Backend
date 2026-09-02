from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.public_intake_models import PublicIntake, PublicIntakeConsent
from app.public_intake_schemas import PublicIntakeAccepted, PublicIntakeCommon
from app.rate_limit import resolved_client_ip


INTAKE_EVENT_TYPES = {
    "CONTACT_REQUEST": "public.contact_request.received.v1",
    "CALLBACK_REQUEST": "public.callback_request.received.v1",
    "LENDER_PARTNER_INQUIRY": "public.lender_partner_inquiry.received.v1",
    "REFERRAL_PARTNER_INQUIRY": "public.referral_partner_inquiry.received.v1",
    "DEAL_SUBMISSION_INQUIRY": "public.deal_submission_inquiry.received.v1",
}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_request_hash(payload: BaseModel) -> str:
    body = _json_value(payload.model_dump(mode="json"))
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def normalize_phone(value: str | None, *, required: bool = False) -> str | None:
    if not value:
        if required:
            raise HTTPException(status_code=422, detail="A phone number is required")
        return None
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        normalized = "+" + digits
    elif len(digits) == 10:
        normalized = "+1" + digits
    elif 8 <= len(digits) <= 15:
        normalized = "+" + digits
    else:
        raise HTTPException(status_code=422, detail="The phone number is invalid")
    if not re.fullmatch(r"\+[1-9]\d{7,14}", normalized):
        raise HTTPException(status_code=422, detail="The phone number is invalid")
    return normalized


def request_evidence(request: Request) -> dict[str, Any]:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    correlation_id = request.headers.get("X-Correlation-ID") or request_id
    client_ip = resolved_client_ip(request)
    return {
        "request_id": request_id,
        "correlation_id": correlation_id,
        "accepted_at": datetime.now(UTC).isoformat(),
        "source_ip_hash": hashlib.sha256(client_ip.encode()).hexdigest() if client_ip else None,
        "user_agent": request.headers.get("User-Agent", "")[:500] or None,
        "origin": request.headers.get("Origin"),
    }


def _normalize_string_list(values: list[str], *, upper: bool = False) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item:
            continue
        item = item.upper() if upper else item
        if item not in normalized:
            normalized.append(item)
    return normalized


def intake_fields(intake_type: str, payload: BaseModel) -> dict[str, Any]:
    data = payload.model_dump(mode="json")
    business_name = (
        data.get("business_name")
        or data.get("institution_name")
        or data.get("company_name")
    )
    subject = data.get("topic") or data.get("reason")
    excluded = {
        "marketing",
        "consents",
        "anti_bot_token",
        "first_name",
        "last_name",
        "email",
        "phone",
        "business_name",
        "institution_name",
        "company_name",
        "message",
        "topic",
        "reason",
    }
    details = {key: value for key, value in data.items() if key not in excluded}
    if "states" in details:
        details["states"] = _normalize_string_list(details["states"], upper=True)
    if "product_types" in details:
        details["product_types"] = _normalize_string_list(details["product_types"])
    return {
        "intake_type": intake_type,
        "first_name": str(data["first_name"]).strip(),
        "last_name": str(data["last_name"]).strip(),
        "email": str(data["email"]).strip().lower(),
        "phone": normalize_phone(
            data.get("phone"),
            required=intake_type in {"CALLBACK_REQUEST", "DEAL_SUBMISSION_INQUIRY"},
        ),
        "business_name": str(business_name).strip() if business_name else None,
        "subject": str(subject).strip() if subject else None,
        "message": str(data.get("message")).strip() if data.get("message") else None,
        "details": _json_value(details),
        "attribution": _json_value(data["marketing"]),
    }


def crm_projection(intake: PublicIntake, consents: list[PublicIntakeConsent]) -> dict[str, Any]:
    return {
        "moneybee_intake_id": str(intake.id),
        "reference": intake.reference,
        "intake_type": intake.intake_type,
        "moneybee_status": intake.status,
        "applicant": {
            "first_name": intake.first_name,
            "last_name": intake.last_name,
            "email": intake.email,
            "phone": intake.phone,
        },
        "business": {"name": intake.business_name},
        "subject": intake.subject,
        "message": intake.message,
        "details": intake.details,
        "marketing": intake.attribution,
        "consent_evidence": [
            {
                "consent_id": str(item.id),
                "type": item.consent_type,
                "document_version": item.document_version,
                "document_hash": item.document_hash,
                "accepted": item.accepted,
                "accepted_at": item.evidence.get("accepted_at"),
            }
            for item in consents
        ],
    }


async def _stored_replay(
    db: AsyncSession,
    *,
    route: str,
    idempotency_key: str,
    request_hash: str,
) -> PublicIntakeAccepted | None:
    row = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == "public",
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IDEMPOTENCY_KEY_CONFLICT",
                "message": "The idempotency key was already used with a different payload.",
            },
        )
    return PublicIntakeAccepted.model_validate(row.response_body)


async def create_public_intake(
    db: AsyncSession,
    *,
    intake_type: str,
    payload: PublicIntakeCommon,
    request: Request,
    idempotency_key: str,
) -> PublicIntakeAccepted:
    route = INTAKE_EVENT_TYPES.get(intake_type)
    if not route:
        raise HTTPException(status_code=500, detail="Unsupported public intake type")
    if not any(consent.accepted for consent in payload.consents):
        raise HTTPException(status_code=422, detail="At least one consent must be accepted")

    request_hash = canonical_request_hash(payload)
    replay = await _stored_replay(
        db,
        route=route,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        return replay

    evidence = request_evidence(request)
    fields = intake_fields(intake_type, payload)
    intake = PublicIntake(
        **fields,
        reference=f"MB-{intake_type.split('_')[0]}-{uuid.uuid4().hex[:12].upper()}",
        source_evidence=evidence,
    )
    db.add(intake)
    await db.flush()

    consent_rows: list[PublicIntakeConsent] = []
    for consent in payload.consents:
        row = PublicIntakeConsent(
            public_intake_id=intake.id,
            consent_type=consent.type,
            document_version=consent.document_version,
            document_hash=consent.document_hash,
            accepted=consent.accepted,
            evidence={
                **evidence,
                "document_hash": consent.document_hash,
            },
        )
        db.add(row)
        consent_rows.append(row)
    await db.flush()

    event_type = INTAKE_EVENT_TYPES[intake_type]
    db.add(
        models.OutboxEvent(
            event_type=event_type,
            schema_version=1,
            aggregate_type="public_intake",
            aggregate_id=intake.id,
            aggregate_version=1,
            tenant_id=None,
            correlation_id=evidence["correlation_id"],
            causation_id=evidence["request_id"],
            payload=crm_projection(intake, consent_rows),
            idempotency_key=f"crm:{intake.id}",
            provider="codestra",
            destination="codestra:crm-projection",
        )
    )
    db.add(
        models.AuditEvent(
            actor_id="public",
            action="PUBLIC_INTAKE_RECEIVED",
            resource_type="public_intake",
            resource_id=str(intake.id),
            request_id=evidence["request_id"],
            details={
                "intake_type": intake_type,
                "reference": intake.reference,
                "request_hash": request_hash,
                "consent_count": len(consent_rows),
            },
        )
    )
    response = PublicIntakeAccepted(
        intake_id=intake.id,
        reference=intake.reference,
        intake_type=intake.intake_type,
        request_id=evidence["request_id"],
    )
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id="public",
            route=route,
            request_hash=request_hash,
            response_status=202,
            response_body=response.model_dump(mode="json"),
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _stored_replay(
            db,
            route=route,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay:
            return replay
        raise
    return response
