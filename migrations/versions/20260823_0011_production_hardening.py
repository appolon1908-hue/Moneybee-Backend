"""Add production hardening records and event metadata.

Revision ID: 20260823_0011
Revises: 20260823_0010
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260823_0011"
down_revision: str | None = "20260823_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "outbox_events",
        sa.Column(
            "aggregate_type",
            sa.String(length=80),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "outbox_events",
        sa.Column("aggregate_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("tenant_id", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("correlation_id", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("causation_id", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("first_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("provider", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("destination", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("last_http_status", sa.Integer(), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_outbox_events_correlation_id",
        "outbox_events",
        ["correlation_id"],
    )

    op.create_table(
        "operational_exceptions",
        sa.Column("fingerprint", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default="OPEN",
            nullable=False,
        ),
        sa.Column("owner_subject", sa.String(length=200), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=160), nullable=False),
        sa.Column("correlation_id", sa.String(length=160), nullable=True),
        sa.Column("retry_action", sa.String(length=160), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column(
            "comments",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("fingerprint"),
    )
    for column in (
        "fingerprint",
        "code",
        "severity",
        "status",
        "resource_type",
        "resource_id",
    ):
        op.create_index(
            f"ix_operational_exceptions_{column}",
            "operational_exceptions",
            [column],
        )

def downgrade() -> None:
    for column in reversed(
        (
            "fingerprint",
            "code",
            "severity",
            "status",
            "resource_type",
            "resource_id",
        )
    ):
        op.drop_index(
            f"ix_operational_exceptions_{column}",
            table_name="operational_exceptions",
        )
    op.drop_table("operational_exceptions")
    op.drop_index("ix_outbox_events_correlation_id", table_name="outbox_events")
    for column in reversed(
        (
            "schema_version",
            "aggregate_type",
            "aggregate_version",
            "tenant_id",
            "correlation_id",
            "causation_id",
            "first_attempt_at",
            "last_attempt_at",
            "delivered_at",
            "provider",
            "destination",
            "last_http_status",
            "last_error_code",
        )
    ):
        op.drop_column("outbox_events", column)
