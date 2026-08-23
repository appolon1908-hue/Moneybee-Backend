import asyncio
import os
import socket
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from app.db import SessionLocal
from app.models import OutboxEvent, OutboxStatus


WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


async def claim() -> str | None:
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
        return str(event.id)


async def deliver(event_id: str) -> None:
    async with SessionLocal() as db:
        event = await db.get(OutboxEvent, event_id)
        if not event or event.lease_owner != WORKER_ID:
            return
        try:
            # Local deterministic provider. Production adapter is configured through Codestra middleware.
            await asyncio.sleep(0)
            event.status = OutboxStatus.DELIVERED
            event.last_error = None
        except Exception as exc:
            event.last_error = str(exc)[:1000]
            event.status = OutboxStatus.DEAD if event.attempt_count >= 8 else OutboxStatus.RETRY
            event.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(3600, 2 ** event.attempt_count)
            )
        finally:
            event.lease_owner = None
            event.lease_expires_at = None
            await db.commit()


async def run() -> None:
    while True:
        event_id = await claim()
        if event_id:
            await deliver(event_id)
        else:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(run())
