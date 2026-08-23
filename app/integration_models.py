from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import Record


class IntegrationInboxMessage(Base, Record):
    __tablename__ = "integration_inbox"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "event_id",
            name="uq_integration_inbox_provider_event",
        ),
    )

    provider: Mapped[str] = mapped_column(String(100), index=True)
    event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(160), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="RECEIVED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OperationalException(Base, Record):
    __tablename__ = "operational_exceptions"

    fingerprint: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="OPEN", index=True)
    owner_subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str] = mapped_column(String(160), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    retry_action: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments: Mapped[list] = mapped_column(JSON, default=list)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
