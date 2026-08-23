import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas


class ConflictError(Exception):
    pass


async def create_application(
    session: AsyncSession, payload: schemas.ApplicationCreate, idempotency_key: str, owner_subject: str
) -> models.Application:
    operation = f"create_application:{owner_subject}"
    existing = await session.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.operation == operation,
            models.IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    if existing:
        application = await session.get(models.Application, existing.resource_id)
        if application is None:
            raise ConflictError("Idempotency record points to a missing application")
        return application

    data = payload.model_dump(exclude={"consent_to_terms"})
    application = models.Application(**data, owner_subject=owner_subject, consented_at=datetime.now(UTC))
    session.add(application)
    await session.flush()
    session.add(
        models.IdempotencyRecord(
            operation=operation,
            idempotency_key=idempotency_key,
            resource_type="application",
            resource_id=application.id,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(models.IdempotencyRecord).where(
                models.IdempotencyRecord.operation == operation,
                models.IdempotencyRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        application = await session.get(models.Application, existing.resource_id)
        if application is None:
            raise ConflictError("Concurrent idempotency record points to a missing application")
        return application
    await session.refresh(application)
    return application


async def create_lead(
    session: AsyncSession, payload: schemas.LeadCreate, idempotency_key: str
) -> models.Lead:
    existing = await session.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.operation == "create_lead",
            models.IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    if existing:
        lead = await session.get(models.Lead, existing.resource_id)
        if lead is None:
            raise ConflictError("Idempotency record points to a missing lead")
        return lead
    lead = models.Lead(**payload.model_dump())
    session.add(lead)
    await session.flush()
    session.add(
        models.IdempotencyRecord(
            operation="create_lead",
            idempotency_key=idempotency_key,
            resource_type="lead",
            resource_id=lead.id,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(models.IdempotencyRecord).where(
                models.IdempotencyRecord.operation == "create_lead",
                models.IdempotencyRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        lead = await session.get(models.Lead, existing.resource_id)
        if lead is None:
            raise ConflictError("Concurrent idempotency record points to a missing lead")
        return lead
    await session.refresh(lead)
    return lead


def transition_application(current: str, target: str) -> str:
    allowed = {
        "draft": {"submitted"},
        "submitted": {"in_review", "declined", "cancelled"},
        "in_review": {"matched", "declined", "cancelled"},
        "matched": {"offer_available", "declined", "cancelled"},
        "offer_available": {"accepted", "cancelled"},
        "accepted": {"funding_pending", "cancelled"},
        "funding_pending": {"funded", "cancelled"},
        "funded": set(),
        "declined": set(),
        "cancelled": set(),
    }
    if target not in allowed.get(current, set()):
        raise ConflictError(f"Invalid application transition: {current} -> {target}")
    return target


def audit_payload(**details: object) -> str:
    return json.dumps(details, separators=(",", ":"), default=str)


def new_correlation_id() -> str:
    return str(uuid.uuid4())
