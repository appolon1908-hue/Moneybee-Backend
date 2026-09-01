"""Stage a nullable external reference for legacy bank credentials.

Revision ID: 20260901_0022a
Revises: 20260901_0022
Create Date: 2026-09-01

This deliberately separate revision gives an operator a supported Alembic
boundary at which to populate and verify external references before the next
revision retires the legacy ciphertext from application use.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0022a"
down_revision: str | None = "20260901_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("bank_provider_states")
    }


def upgrade() -> None:
    if "credential_reference" in _columns():
        return
    op.add_column(
        "bank_provider_states",
        sa.Column("credential_reference", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    if "credential_reference" not in _columns():
        return
    populated = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM bank_provider_states "
            "WHERE credential_reference IS NOT NULL"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError(
            "downgrade would discard staged external credential references"
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("bank_provider_states") as batch_op:
            batch_op.drop_column("credential_reference")
    else:
        op.drop_column("bank_provider_states", "credential_reference")
