"""Add lender submission assignment metadata.

Revision ID: 20260828_0019
Revises: 20260827_0018
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_0019"
down_revision: str | None = "20260827_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lender_submissions",
        sa.Column("assigned_to_subject", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_lender_submissions_assigned_to_subject",
        "lender_submissions",
        ["assigned_to_subject"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lender_submissions_assigned_to_subject",
        table_name="lender_submissions",
    )
    op.drop_column("lender_submissions", "assigned_to_subject")
