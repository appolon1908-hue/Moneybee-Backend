"""Add contract uniqueness and durable inbox retry scheduling.

Revision ID: 20260901_0025
Revises: 20260901_0024
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0025"
down_revision: str | None = "20260901_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text("SELECT offer_id FROM contracts GROUP BY offer_id HAVING count(*) > 1 LIMIT 1")
    ).first()
    if duplicate is not None:
        raise RuntimeError("Cannot enforce one contract per offer while duplicate contracts exist")
    op.add_column("integration_inbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.create_index("ix_integration_inbox_next_attempt_at", "integration_inbox", ["next_attempt_at"])
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("contracts") as batch:
            batch.create_unique_constraint("uq_contract_offer", ["offer_id"])
    else:
        op.create_unique_constraint("uq_contract_offer", "contracts", ["offer_id"])


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("contracts") as batch:
            batch.drop_constraint("uq_contract_offer", type_="unique")
    else:
        op.drop_constraint("uq_contract_offer", "contracts", type_="unique")
    op.drop_index("ix_integration_inbox_next_attempt_at", table_name="integration_inbox")
    op.drop_column("integration_inbox", "next_attempt_at")
