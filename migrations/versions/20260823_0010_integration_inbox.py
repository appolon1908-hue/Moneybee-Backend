"""Add durable integration inbox.

Revision ID: 20260823_0010
Revises: 20260823_0009
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260823_0010"
down_revision: str | None = "20260823_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE capability_flags SET provider = 'middleware' "
            "WHERE key = 'crm.write' AND provider = 'crm'"
        )
    )
    op.create_table(
        "integration_inbox",
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=160), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "signature_valid",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default="RECEIVED",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "event_id",
            name="uq_integration_inbox_provider_event",
        ),
    )
    op.create_index(
        "ix_integration_inbox_provider",
        "integration_inbox",
        ["provider"],
    )
    op.create_index(
        "ix_integration_inbox_event_type",
        "integration_inbox",
        ["event_type"],
    )
    op.create_index(
        "ix_integration_inbox_status",
        "integration_inbox",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_integration_inbox_status", table_name="integration_inbox")
    op.drop_index("ix_integration_inbox_event_type", table_name="integration_inbox")
    op.drop_index("ix_integration_inbox_provider", table_name="integration_inbox")
    op.drop_table("integration_inbox")
    op.execute(
        sa.text(
            "UPDATE capability_flags SET provider = 'crm' "
            "WHERE key = 'crm.write' AND provider = 'middleware'"
        )
    )
