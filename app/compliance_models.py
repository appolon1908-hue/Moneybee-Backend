import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from decimal import Decimal

from app.db_base import Base
from app.models import Record


class AdverseActionNotice(Base, Record):
    """A record of an ECOA/Regulation B adverse-action notice for one
    lender's decline decision on one application. notice_text is the
    rendered notice at generation time - kept immutable once generated,
    matching how an actually-sent notice can't be silently edited after
    the fact."""

    __tablename__ = "adverse_action_notices"
    __table_args__ = (
        UniqueConstraint(
            "underwriting_review_id", name="uq_adverse_action_notice_review"
        ),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lender_submissions.id"), index=True
    )
    underwriting_review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("underwriting_reviews.id"), index=True
    )
    lender_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    creditor_name: Mapped[str] = mapped_column(String(255))
    principal_reasons: Mapped[list] = mapped_column(JSON, default=list)
    notice_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="GENERATED")
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CommercialFinancingDisclosure(Base, Record):
    """A commercial-financing cost disclosure for one offer, in the shape
    California SB 1235 (Cal. Fin. Code Sec. 22800 et seq.) and similar
    state commercial-financing disclosure laws require: total cost of
    financing, an APR or APR-equivalent, payment amount/frequency, term,
    and prepayment policy. The calculation is real; the exact layout and
    which states it must be issued in is not - see the generation
    service's docstring."""

    __tablename__ = "commercial_financing_disclosures"

    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offers.id"), unique=True, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    jurisdiction: Mapped[str | None] = mapped_column(String(2), nullable=True)
    amount_financed: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    finance_charge: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_repayment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    estimated_apr: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    payment_frequency: Mapped[str] = mapped_column(String(40))
    term_months: Mapped[int] = mapped_column()
    prepayment_policy: Mapped[str] = mapped_column(Text)
    disclosure_text: Mapped[str] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CommissionTaxRecord(Base, Record):
    """One payee's aggregated commission-receipt total for one tax year -
    the data a 1099-NEC (Box 1: Nonemployee compensation) would be filed
    from. Generation is idempotent per (recipient_reference, tax_year):
    re-running it recomputes the total from CommissionReceipt rows rather
    than accumulating. tin_ciphertext is encrypted via
    app/encryption.py's versioned scheme - never stored or returned in
    the clear."""

    __tablename__ = "commission_tax_records"
    __table_args__ = (
        UniqueConstraint(
            "recipient_type", "recipient_reference", "tax_year",
            name="uq_commission_tax_record_type_recipient_year"
        ),
    )

    recipient_type: Mapped[str] = mapped_column(String(50))
    recipient_reference: Mapped[str] = mapped_column(String(255), index=True)
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tin_ciphertext: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tax_year: Mapped[int] = mapped_column(index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    commission_count: Mapped[int] = mapped_column()
    requires_1099: Mapped[bool] = mapped_column(Boolean, default=False)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filing_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
