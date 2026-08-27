import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import Record


class LedgerAccount(Base, Record):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_ledger_account_org_code",
        ),
        CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE')",
            name="ck_ledger_accounts_type",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        index=True,
    )
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    account_type: Mapped[str] = mapped_column(String(20), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    active: Mapped[bool] = mapped_column(default=True, index=True)
    system_managed: Mapped[bool] = mapped_column(default=False)


class AccountingPeriod(Base, Record):
    __tablename__ = "accounting_periods"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_accounting_period_org_name",
        ),
        CheckConstraint(
            "status IN ('OPEN','CLOSED','LOCKED')",
            name="ck_accounting_period_status",
        ),
        CheckConstraint(
            "ends_at > starts_at",
            name="ck_accounting_period_range",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class JournalEntry(Base, Record):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "entry_number",
            name="uq_journal_entry_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_journal_entry_org_idempotency",
        ),
        CheckConstraint(
            "status IN ('POSTED','VOID')",
            name="ck_journal_entry_status",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        index=True,
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounting_periods.id"),
        nullable=True,
        index=True,
    )
    entry_number: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(80), index=True)
    source_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="POSTED", index=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[str] = mapped_column(String(255))
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id"),
        nullable=True,
    )
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class JournalPosting(Base, Record):
    __tablename__ = "journal_postings"
    __table_args__ = (
        CheckConstraint(
            "side IN ('DEBIT','CREDIT')",
            name="ck_journal_posting_side",
        ),
        CheckConstraint(
            "amount > 0",
            name="ck_journal_posting_amount",
        ),
    )

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        index=True,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ledger_accounts.id"),
        index=True,
    )
    side: Mapped[str] = mapped_column(String(10), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id"),
        nullable=True,
        index=True,
    )
    funding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fundings.id"),
        nullable=True,
        index=True,
    )
    commission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("commissions.id"),
        nullable=True,
        index=True,
    )
    bank_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bank_transactions.id"),
        nullable=True,
        index=True,
    )
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class FinancialSettlement(Base, Record):
    __tablename__ = "financial_settlements"
    __table_args__ = (
        CheckConstraint(
            "settlement_type IN ('FUNDING','COMMISSION','FEE','REFUND','ADJUSTMENT')",
            name="ck_financial_settlement_type",
        ),
        CheckConstraint(
            "status IN ('PENDING','RECORDED','RECONCILED','FAILED','VOID')",
            name="ck_financial_settlement_status",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_financial_settlement_amount",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        index=True,
    )
    settlement_type: Mapped[str] = mapped_column(String(30), index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id"),
        nullable=True,
        index=True,
    )
    funding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fundings.id"),
        nullable=True,
        index=True,
    )
    commission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("commissions.id"),
        nullable=True,
        index=True,
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id"),
        nullable=True,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    external_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reconciliation_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
