from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base
from app.models import Record


class PublicIntake(Base, Record):
    __tablename__ = "public_intakes"
    __table_args__ = (
        UniqueConstraint("reference", name="uq_public_intake_reference"),
    )

    intake_type: Mapped[str] = mapped_column(String(80), index=True)
    reference: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="RECEIVED", index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    business_name: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    subject: Mapped[str | None] = mapped_column(String(240), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    attribution: Mapped[dict] = mapped_column(JSON, default=dict)
    source_evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class PublicIntakeConsent(Base, Record):
    __tablename__ = "public_intake_consents"

    public_intake_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_intakes.id", ondelete="CASCADE"),
        index=True,
    )
    consent_type: Mapped[str] = mapped_column(String(100), index=True)
    document_version: Mapped[str] = mapped_column(String(80))
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted: Mapped[bool] = mapped_column(default=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
