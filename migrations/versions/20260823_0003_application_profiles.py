"""Add borrower-owned application profile sections.

Revision ID: 20260823_0003
Revises: 20260823_0002
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260823_0003"
down_revision: str | None = "20260823_0002"
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
    op.add_column(
        "applications",
        sa.Column("borrower_subject", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_applications_borrower_subject",
        "applications",
        ["borrower_subject"],
    )

    op.create_table(
        "application_status_history",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=80), nullable=True),
        sa.Column("to_status", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        *record_columns(),
    )
    op.create_index(
        "ix_application_status_history_application_id",
        "application_status_history",
        ["application_id"],
    )

    op.create_table(
        "businesses",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.String(length=240), nullable=False),
        sa.Column("dba", sa.String(length=240), nullable=True),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("state_formed", sa.String(length=2), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("naics", sa.String(length=12), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("address", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.UniqueConstraint("application_id"),
        *record_columns(),
    )
    op.create_index("ix_businesses_application_id", "businesses", ["application_id"])

    op.create_table(
        "owners",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("ownership_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("address", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        *record_columns(),
    )
    op.create_index("ix_owners_application_id", "owners", ["application_id"])

    op.create_table(
        "financial_profiles",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("annual_revenue", sa.Numeric(18, 2), nullable=True),
        sa.Column("monthly_revenue", sa.Numeric(18, 2), nullable=True),
        sa.Column("monthly_expenses", sa.Numeric(18, 2), nullable=True),
        sa.Column("existing_debt", sa.Numeric(18, 2), nullable=True),
        sa.Column("existing_positions", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.UniqueConstraint("application_id"),
        *record_columns(),
    )
    op.create_index(
        "ix_financial_profiles_application_id",
        "financial_profiles",
        ["application_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_financial_profiles_application_id",
        table_name="financial_profiles",
    )
    op.drop_table("financial_profiles")
    op.drop_index("ix_owners_application_id", table_name="owners")
    op.drop_table("owners")
    op.drop_index("ix_businesses_application_id", table_name="businesses")
    op.drop_table("businesses")
    op.drop_index(
        "ix_application_status_history_application_id",
        table_name="application_status_history",
    )
    op.drop_table("application_status_history")
    op.drop_index("ix_applications_borrower_subject", table_name="applications")
    op.drop_column("applications", "borrower_subject")
