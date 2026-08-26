from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class LenderPortalDecision(Base):
    __tablename__ = "lender_portal_decisions"
    __table_args__ = (
        UniqueConstraint(
            "lender_id",
            "submission_id",
            "idempotency_key",
            name="uq_lender_portal_decision_command",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    lender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lenders.id", ondelete="CASCADE"), index=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lender_submissions.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(40), index=True)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="PENDING_REVIEW", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
