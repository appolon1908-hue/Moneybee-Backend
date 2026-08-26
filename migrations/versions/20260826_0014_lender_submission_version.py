"""Add optimistic concurrency version to lender submissions.

Revision ID: 20260826_0014
Revises: 20260826_0013
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_0014"
down_revision: str | None = "20260826_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lender_submissions",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("lender_submissions", "version")
