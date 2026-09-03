"""Require durable split-payment evidence for tax attribution.

Revision ID: 20260902_0027
Revises: 20260901_0026
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260902_0027"
down_revision: str | None = "20260901_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("commission_splits") as batch:
        batch.add_column(sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("payment_reference", sa.String(length=255), nullable=True))
        batch.create_check_constraint(
            "ck_commission_split_paid_evidence",
            "status != 'PAID' OR (paid_at IS NOT NULL AND payment_reference IS NOT NULL)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    paid = bind.execute(sa.text(
        "SELECT 1 FROM commission_splits "
        "WHERE status = 'PAID' OR paid_at IS NOT NULL OR payment_reference IS NOT NULL LIMIT 1"
    )).first()
    if paid is not None:
        raise RuntimeError("Downgrade would strand commission split payment evidence")
    with op.batch_alter_table("commission_splits") as batch:
        batch.drop_constraint("ck_commission_split_paid_evidence", type_="check")
        batch.drop_column("payment_reference")
        batch.drop_column("paid_at")
