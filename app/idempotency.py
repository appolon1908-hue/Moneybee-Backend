from __future__ import annotations

import hashlib

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models


def _postgres_lock_id(actor_id: str, route: str, key: str) -> int:
    digest = hashlib.sha256(f"{actor_id}\0{route}\0{key}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big", signed=False)
    return value if value < 2**63 else value - 2**64


async def acquire_idempotency_lock(
    db: AsyncSession,
    *,
    actor_id: str,
    route: str,
    key: str,
) -> None:
    """Serialize one actor/route/key for the current transaction.

    PostgreSQL row locks cannot protect a not-yet-created idempotency record.
    A transaction-scoped advisory lock closes that insertion race without a
    schema change. SQLite tests are already single-writer and need no extra
    primitive.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": _postgres_lock_id(actor_id, route, key)},
    )


async def get_idempotency_record(
    db: AsyncSession,
    *,
    actor_id: str,
    route: str,
    key: str,
) -> models.IdempotencyRecord | None:
    return await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == actor_id,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == key,
        )
    )
