import asyncio
import os
import socket
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from app.db import SessionLocal
from app.integrations.base import ProviderError
from app.integrations.middleware import canonical_event_type
from app.integrations.registry import middleware_adapter
from app.integration_models import OperationalException
from app.models import IntegrationEvent, OutboxEvent, OutboxStatus
from app.services import effective_capabilities


WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def external_delivery_enabled() -> bool:
    """Require an explicit runtime gate before leasing or sending any event."""
    return os.getenv("ENABLE_EXTERNAL_DELIVERY", "false").strip().lower() in TRUE_VALUES


async def claim() -> str | None:
    if not external_delivery_enabled():
        return None

    now = datetime.now(UTC)
    async with SessionLocal() as db, db.begin():
        event = await db.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.RETRY]),
                or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
                or_(OutboxEvent.lease_expires_at.is_(None), OutboxEvent.lease_expires_at < now),
            )
            .order_by(OutboxEvent.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not event:
            return None
        event.status = OutboxStatus.LEASED
        event.lease_owner = WORKER_ID
        event.lease_expires_at = now + timedelta(seconds=60)
        event.attempt_count += 1
        event.first_attempt_at = event.first_attempt_at or now
        event.last_attempt_at = now
        event.provider = "codestra"
        event.destination = "codestra:event-ingress"
        return str(event.id)


async def deliver(event_id: str) -> None:
    async with SessionLocal() as db:
        event = await db.get(OutboxEvent, event_id)
        if not event or event.lease_owner != WORKER_ID:
            return
        if not external_delivery_enabled():
            event.status = OutboxStatus.PENDING
            event.lease_owner = None
            event.lease_expires_at = None
            await db.commit()
            return

        try:
            capabilities = await effective_capabilities(db)
            if not capabilities.get("crm.write", False):
                raise ProviderError(
                    "codestra",
                    "crm.write is not enabled and provider-ready",
                )
            adapter = middleware_adapter()
            canonical_type = canonical_event_type(event.event_type)
            result = await adapter.publish(
                event_id=str(event.id),
                event_type=canonical_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=str(event.aggregate_id),
                aggregate_version=event.aggregate_version,
                tenant_id=event.tenant_id,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                occurred_at=event.created_at.isoformat(),
                payload=event.payload,
            )
            db.add(
                IntegrationEvent(
                    provider=result.provider,
                    event_type=canonical_type,
                    aggregate_id=event.aggregate_id,
                    status="DELIVERED",
                    attempts=event.attempt_count,
                    external_id=result.external_id,
                    response=result.response,
                )
            )
            event.status = OutboxStatus.DELIVERED
            event.delivered_at = datetime.now(UTC)
            event.last_error = None
            event.last_error_code = None
        except Exception as exc:
            event.last_error = str(exc)[:1000]
            event.last_error_code = type(exc).__name__[:120]
            event.last_http_status = (
                exc.status_code if isinstance(exc, ProviderError) else None
            )
            db.add(
                IntegrationEvent(
                    provider="codestra",
                    event_type=canonical_event_type(event.event_type),
                    aggregate_id=event.aggregate_id,
                    status="FAILED",
                    attempts=event.attempt_count,
                    last_error=event.last_error,
                )
            )
            terminal = event.attempt_count >= 8
            event.status = OutboxStatus.DEAD if terminal else OutboxStatus.RETRY
            event.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(3600, 2 ** event.attempt_count)
            )
            if terminal:
                fingerprint = f"OUTBOX_RETRY_EXHAUSTED:{event.id}"
                existing = await db.scalar(
                    select(OperationalException).where(
                        OperationalException.fingerprint == fingerprint
                    )
                )
                if existing is None:
                    db.add(
                        OperationalException(
                            fingerprint=fingerprint,
                            code="OUTBOX_RETRY_EXHAUSTED",
                            severity="HIGH",
                            resource_type="outbox_event",
                            resource_id=str(event.id),
                            correlation_id=event.correlation_id,
                            retry_action="REPLAY_OUTBOX_EVENT",
                            comments=[],
                        )
                    )
        finally:
            event.lease_owner = None
            event.lease_expires_at = None
            await db.commit()


async def run() -> None:
    while True:
        if not external_delivery_enabled():
            await asyncio.sleep(5)
            continue
        event_id = await claim()
        if event_id:
            await deliver(event_id)
        else:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(run())