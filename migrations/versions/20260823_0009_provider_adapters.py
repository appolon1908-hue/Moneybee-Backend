"""Add provider adapter banking state.

Revision ID: 20260823_0009
Revises: 20260823_0008
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260823_0009"
down_revision: str | None = "20260823_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "bank_provider_states",
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("bank_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=True),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("transaction_cursor", sa.Text(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id"),
    )
    op.create_index(
        "ix_bank_provider_states_connection_id",
        "bank_provider_states",
        ["connection_id"],
    )
    op.create_index(
        "ix_bank_provider_states_item_id",
        "bank_provider_states",
        ["item_id"],
    )

    op.create_table(
        "bank_accounts",
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("bank_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_account_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("official_name", sa.String(length=500), nullable=True),
        sa.Column("mask", sa.String(length=20), nullable=True),
        sa.Column("account_type", sa.String(length=80), nullable=True),
        sa.Column("subtype", sa.String(length=80), nullable=True),
        sa.Column("current_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("available_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "provider_account_id",
            name="uq_bank_account_provider_identity",
        ),
    )
    op.create_index(
        "ix_bank_accounts_connection_id",
        "bank_accounts",
        ["connection_id"],
    )
    op.create_index(
        "ix_bank_accounts_provider_account_id",
        "bank_accounts",
        ["provider_account_id"],
    )

    op.create_table(
        "bank_balance_snapshots",
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("bank_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("current_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("available_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bank_balance_snapshots_account_id",
        "bank_balance_snapshots",
        ["account_id"],
    )
    op.create_index(
        "ix_bank_balance_snapshots_captured_at",
        "bank_balance_snapshots",
        ["captured_at"],
    )

    op.create_table(
        "bank_transactions",
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("bank_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("bank_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column(
            "provider_transaction_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("merchant_name", sa.String(length=500), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("pending", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("removed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_transaction_id",
            name="uq_bank_transaction_provider_identity",
        ),
    )
    op.create_index(
        "ix_bank_transactions_connection_id",
        "bank_transactions",
        ["connection_id"],
    )
    op.create_index(
        "ix_bank_transactions_account_id",
        "bank_transactions",
        ["account_id"],
    )
    op.create_index(
        "ix_bank_transactions_provider_transaction_id",
        "bank_transactions",
        ["provider_transaction_id"],
    )
    op.create_index(
        "ix_bank_transactions_posted_at",
        "bank_transactions",
        ["posted_at"],
    )

    op.create_table(
        "webhook_receipts",
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=160), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default="RECEIVED",
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_webhook_receipt_provider_event",
        ),
    )
    op.create_index(
        "ix_webhook_receipts_provider",
        "webhook_receipts",
        ["provider"],
    )
    op.create_index(
        "ix_webhook_receipts_status",
        "webhook_receipts",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_receipts_status", table_name="webhook_receipts")
    op.drop_index("ix_webhook_receipts_provider", table_name="webhook_receipts")
    op.drop_table("webhook_receipts")
    op.drop_index("ix_bank_transactions_posted_at", table_name="bank_transactions")
    op.drop_index(
        "ix_bank_transactions_provider_transaction_id",
        table_name="bank_transactions",
    )
    op.drop_index("ix_bank_transactions_account_id", table_name="bank_transactions")
    op.drop_index(
        "ix_bank_transactions_connection_id",
        table_name="bank_transactions",
    )
    op.drop_table("bank_transactions")
    op.drop_index(
        "ix_bank_balance_snapshots_captured_at",
        table_name="bank_balance_snapshots",
    )
    op.drop_index(
        "ix_bank_balance_snapshots_account_id",
        table_name="bank_balance_snapshots",
    )
    op.drop_table("bank_balance_snapshots")
    op.drop_index(
        "ix_bank_accounts_provider_account_id",
        table_name="bank_accounts",
    )
    op.drop_index("ix_bank_accounts_connection_id", table_name="bank_accounts")
    op.drop_table("bank_accounts")
    op.drop_index(
        "ix_bank_provider_states_item_id",
        table_name="bank_provider_states",
    )
    op.drop_index(
        "ix_bank_provider_states_connection_id",
        table_name="bank_provider_states",
    )
    op.drop_table("bank_provider_states")
