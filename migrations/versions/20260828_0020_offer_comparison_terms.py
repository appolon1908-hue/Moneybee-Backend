"""Add prepayment terms, guarantee, and collateral fields to offers.

Revision ID: 20260828_0020
Revises: 20260828_0019
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_0020"
down_revision: str | None = "20260828_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("offers", sa.Column("prepayment_terms", sa.Text(), nullable=True))
    op.add_column(
        "offers",
        sa.Column(
            "personal_guarantee_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("offers", sa.Column("collateral_description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("offers", "collateral_description")
    op.drop_column("offers", "personal_guarantee_required")
    op.drop_column("offers", "prepayment_terms")
