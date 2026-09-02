"""Align commission tax-record uniqueness with recipient type.

Revision ID: 20260901_0026
Revises: 20260901_0025
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20260901_0026"
down_revision: str | None = "20260901_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    with op.batch_alter_table("commission_tax_records") as batch:
        batch.drop_constraint("uq_commission_tax_record_recipient_year", type_="unique")
        batch.create_unique_constraint(
            "uq_commission_tax_record_type_recipient_year",
            ["recipient_type", "recipient_reference", "tax_year"],
        )

def downgrade() -> None:
    duplicate = op.get_bind().execute(sa.text(
        "SELECT recipient_reference, tax_year FROM commission_tax_records "
        "GROUP BY recipient_reference, tax_year HAVING count(*) > 1 LIMIT 1"
    )).first()
    if duplicate is not None:
        raise RuntimeError("Downgrade would merge distinct recipient-type tax records")
    with op.batch_alter_table("commission_tax_records") as batch:
        batch.drop_constraint("uq_commission_tax_record_type_recipient_year", type_="unique")
        batch.create_unique_constraint(
            "uq_commission_tax_record_recipient_year", ["recipient_reference", "tax_year"]
        )
