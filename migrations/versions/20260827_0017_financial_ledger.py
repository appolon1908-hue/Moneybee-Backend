"""Add tenant-scoped double-entry financial ledger.

Revision ID: 20260827_0017
Revises: 20260826_0016
Create Date: 2026-08-26
"""

from collections.abc import Sequence
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0017"
down_revision: str | None = "20260826_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ledger_accounts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("system_managed", sa.Boolean(), server_default=sa.false(), nullable=False),
        *record_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_ledger_account_org_code"),
        sa.CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE')",
            name="ck_ledger_accounts_type",
        ),
    )
    for column in ("organization_id", "account_type", "active"):
        op.create_index(f"ix_ledger_accounts_{column}", "ledger_accounts", [column])

    op.create_table(
        "accounting_periods",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="OPEN", nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(length=255), nullable=True),
        *record_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_accounting_period_org_name"),
        sa.CheckConstraint("status IN ('OPEN','CLOSED','LOCKED')", name="ck_accounting_period_status"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_accounting_period_range"),
    )
    for column in ("organization_id", "starts_at", "ends_at", "status"):
        op.create_index(f"ix_accounting_periods_{column}", "accounting_periods", [column])

    op.create_table(
        "journal_entries",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=True),
        sa.Column("entry_number", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="POSTED", nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_by", sa.String(length=255), nullable=False),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        *record_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["period_id"], ["accounting_periods.id"]),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["journal_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "entry_number", name="uq_journal_entry_org_number"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_journal_entry_org_idempotency"),
        sa.CheckConstraint("status IN ('POSTED','VOID')", name="ck_journal_entry_status"),
    )
    for column in ("organization_id", "period_id", "source_type", "source_id", "effective_at", "status"):
        op.create_index(f"ix_journal_entries_{column}", "journal_entries", [column])

    op.create_table(
        "journal_postings",
        sa.Column("journal_entry_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("funding_id", sa.Uuid(), nullable=True),
        sa.Column("commission_id", sa.Uuid(), nullable=True),
        sa.Column("bank_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("memo", sa.String(length=500), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        *record_columns(),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["ledger_accounts.id"]),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["funding_id"], ["fundings.id"]),
        sa.ForeignKeyConstraint(["commission_id"], ["commissions.id"]),
        sa.ForeignKeyConstraint(["bank_transaction_id"], ["bank_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("side IN ('DEBIT','CREDIT')", name="ck_journal_posting_side"),
        sa.CheckConstraint("amount > 0", name="ck_journal_posting_amount"),
    )
    for column in (
        "journal_entry_id",
        "account_id",
        "side",
        "application_id",
        "funding_id",
        "commission_id",
        "bank_transaction_id",
    ):
        op.create_index(f"ix_journal_postings_{column}", "journal_postings", [column])

    op.create_table(
        "financial_settlements",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("settlement_type", sa.String(length=30), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("funding_id", sa.Uuid(), nullable=True),
        sa.Column("commission_id", sa.Uuid(), nullable=True),
        sa.Column("journal_entry_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciliation_metadata", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        *record_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["funding_id"], ["fundings.id"]),
        sa.ForeignKeyConstraint(["commission_id"], ["commissions.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "settlement_type IN ('FUNDING','COMMISSION','FEE','REFUND','ADJUSTMENT')",
            name="ck_financial_settlement_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RECORDED','RECONCILED','FAILED','VOID')",
            name="ck_financial_settlement_status",
        ),
        sa.CheckConstraint("amount >= 0", name="ck_financial_settlement_amount"),
    )
    for column in (
        "organization_id",
        "settlement_type",
        "application_id",
        "funding_id",
        "commission_id",
        "journal_entry_id",
        "status",
        "external_reference",
    ):
        op.create_index(f"ix_financial_settlements_{column}", "financial_settlements", [column])

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    op.bulk_insert(
        permissions,
        [
            {"id": uuid.uuid4(), "code": "finance.read", "description": "Read tenant accounting records and trial balances"},
            {"id": uuid.uuid4(), "code": "finance.post", "description": "Post balanced journal entries"},
            {"id": uuid.uuid4(), "code": "finance.manage", "description": "Manage chart of accounts and accounting periods"},
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE code IN ('finance.read','finance.post','finance.manage')")
    for column in reversed((
        "organization_id", "settlement_type", "application_id", "funding_id", "commission_id",
        "journal_entry_id", "status", "external_reference",
    )):
        op.drop_index(f"ix_financial_settlements_{column}", table_name="financial_settlements")
    op.drop_table("financial_settlements")

    for column in reversed((
        "journal_entry_id", "account_id", "side", "application_id", "funding_id",
        "commission_id", "bank_transaction_id",
    )):
        op.drop_index(f"ix_journal_postings_{column}", table_name="journal_postings")
    op.drop_table("journal_postings")

    for column in reversed(("organization_id", "period_id", "source_type", "source_id", "effective_at", "status")):
        op.drop_index(f"ix_journal_entries_{column}", table_name="journal_entries")
    op.drop_table("journal_entries")

    for column in reversed(("organization_id", "starts_at", "ends_at", "status")):
        op.drop_index(f"ix_accounting_periods_{column}", table_name="accounting_periods")
    op.drop_table("accounting_periods")

    for column in reversed(("organization_id", "account_type", "active")):
        op.drop_index(f"ix_ledger_accounts_{column}", table_name="ledger_accounts")
    op.drop_table("ledger_accounts")
