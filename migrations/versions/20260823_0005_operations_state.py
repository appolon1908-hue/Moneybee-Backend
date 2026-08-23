"""Add reconciliation and notification operations state.

Revision ID: 20260823_0005
Revises: 20260823_0004
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260823_0005"
down_revision: str | None = "20260823_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.create_table(
        "reconciliation_runs",
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("checked", sa.Integer(), nullable=False),
        sa.Column("mismatches", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *record_columns(),
    )
    op.create_index(
        "ix_reconciliation_runs_provider",
        "reconciliation_runs",
        ["provider"],
    )
    op.create_index(
        "ix_reconciliation_runs_status",
        "reconciliation_runs",
        ["status"],
    )

    op.create_table(
        "reconciliation_items",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["reconciliation_runs.id"],
            ondelete="CASCADE",
        ),
        *record_columns(),
    )
    op.create_index(
        "ix_reconciliation_items_run_id",
        "reconciliation_items",
        ["run_id"],
    )
    op.create_index(
        "ix_reconciliation_items_status",
        "reconciliation_items",
        ["status"],
    )

    op.create_table(
        "communication_templates",
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("code"),
        *record_columns(),
    )
    op.create_index(
        "ix_communication_templates_code",
        "communication_templates",
        ["code"],
    )

    op.create_table(
        "notification_preferences",
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False),
        sa.Column("sms_enabled", sa.Boolean(), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("subject"),
        *record_columns(),
    )
    op.create_index(
        "ix_notification_preferences_subject",
        "notification_preferences",
        ["subject"],
    )

    op.create_table(
        "document_reviews",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_subject", sa.String(255), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        *record_columns(),
    )
    op.create_index(
        "ix_document_reviews_document_id",
        "document_reviews",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_reviews_document_id", table_name="document_reviews")
    op.drop_table("document_reviews")
    op.drop_index(
        "ix_notification_preferences_subject",
        table_name="notification_preferences",
    )
    op.drop_table("notification_preferences")
    op.drop_index(
        "ix_communication_templates_code",
        table_name="communication_templates",
    )
    op.drop_table("communication_templates")
    op.drop_index(
        "ix_reconciliation_items_status",
        table_name="reconciliation_items",
    )
    op.drop_index(
        "ix_reconciliation_items_run_id",
        table_name="reconciliation_items",
    )
    op.drop_table("reconciliation_items")
    op.drop_index(
        "ix_reconciliation_runs_status",
        table_name="reconciliation_runs",
    )
    op.drop_index(
        "ix_reconciliation_runs_provider",
        table_name="reconciliation_runs",
    )
    op.drop_table("reconciliation_runs")
