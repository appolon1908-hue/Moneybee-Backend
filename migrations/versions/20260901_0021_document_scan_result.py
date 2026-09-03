"""Add malware scan result fields to documents.

Revision ID: 20260901_0021
Revises: 20260828_0020
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0021"
down_revision: str | None = "20260828_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("scan_provider", sa.String(40), nullable=True))
    op.add_column("documents", sa.Column("scan_result", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "scanned_at")
    op.drop_column("documents", "scan_result")
    op.drop_column("documents", "scan_provider")
