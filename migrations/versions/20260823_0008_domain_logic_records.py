"""Add authoritative domain logic records.

Revision ID: 20260823_0008
Revises: 20260823_0007
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260823_0008"
down_revision: str | None = "20260823_0007"
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
        "requirement_snapshots",
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("completion_percentage", sa.Integer(), nullable=False),
        sa.Column(
            "ready_for_submission",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "ready_for_contract",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "ready_for_funding",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("requirements", sa.JSON(), nullable=False),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_requirement_snapshots_application_id",
        "requirement_snapshots",
        ["application_id"],
    )

    op.create_table(
        "underwriting_reviews",
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("applications.id"),
            nullable=False,
        ),
        sa.Column(
            "submission_id",
            sa.Uuid(),
            sa.ForeignKey("lender_submissions.id"),
            nullable=True,
        ),
        sa.Column("reviewer_subject", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_underwriting_reviews_application_id",
        "underwriting_reviews",
        ["application_id"],
    )
    op.create_index(
        "ix_underwriting_reviews_submission_id",
        "underwriting_reviews",
        ["submission_id"],
    )

    op.create_table(
        "commission_splits",
        sa.Column(
            "commission_id",
            sa.Uuid(),
            sa.ForeignKey("commissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_type", sa.String(length=50), nullable=False),
        sa.Column("recipient_reference", sa.String(length=255), nullable=False),
        sa.Column("percentage", sa.Numeric(8, 4), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default="PENDING",
            nullable=False,
        ),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_commission_splits_commission_id",
        "commission_splits",
        ["commission_id"],
    )

    op.create_table(
        "commission_adjustments",
        sa.Column(
            "commission_id",
            sa.Uuid(),
            sa.ForeignKey("commissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("adjustment_type", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_commission_adjustments_commission_id",
        "commission_adjustments",
        ["commission_id"],
    )

    op.create_table(
        "sla_alerts",
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("applications.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column(
            "severity",
            sa.String(length=30),
            server_default="WARNING",
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default="OPEN",
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sla_alerts_application_id", "sla_alerts", ["application_id"])
    op.create_index("ix_sla_alerts_code", "sla_alerts", ["code"])
    op.create_index("ix_sla_alerts_status", "sla_alerts", ["status"])

    op.create_table(
        "user_accounts",
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject"),
    )
    op.create_index("ix_user_accounts_subject", "user_accounts", ["subject"])
    op.create_index("ix_user_accounts_email", "user_accounts", ["email"])


def downgrade() -> None:
    op.drop_index("ix_user_accounts_email", table_name="user_accounts")
    op.drop_index("ix_user_accounts_subject", table_name="user_accounts")
    op.drop_table("user_accounts")
    op.drop_index("ix_sla_alerts_status", table_name="sla_alerts")
    op.drop_index("ix_sla_alerts_code", table_name="sla_alerts")
    op.drop_index("ix_sla_alerts_application_id", table_name="sla_alerts")
    op.drop_table("sla_alerts")
    op.drop_index(
        "ix_commission_adjustments_commission_id",
        table_name="commission_adjustments",
    )
    op.drop_table("commission_adjustments")
    op.drop_index(
        "ix_commission_splits_commission_id",
        table_name="commission_splits",
    )
    op.drop_table("commission_splits")
    op.drop_index(
        "ix_underwriting_reviews_submission_id",
        table_name="underwriting_reviews",
    )
    op.drop_index(
        "ix_underwriting_reviews_application_id",
        table_name="underwriting_reviews",
    )
    op.drop_table("underwriting_reviews")
    op.drop_index(
        "ix_requirement_snapshots_application_id",
        table_name="requirement_snapshots",
    )
    op.drop_table("requirement_snapshots")
