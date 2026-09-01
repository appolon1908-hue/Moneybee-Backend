"""Stage bank-provider credentials behind an external secret reference.

Revision ID: 20260901_0023
Revises: 20260901_0022
Create Date: 2026-09-01

The legacy encrypted column is intentionally retained during the compatibility
window. The application does not read or write it after this migration.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0023"
down_revision: str | None = "20260901_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("bank_provider_states")}
    if "credential_reference" in columns and "access_token_ciphertext" not in columns:
        return
    if "access_token_ciphertext" not in columns:
        raise RuntimeError("bank_provider_states has no recognized credential column")

    unresolved = connection.execute(
        sa.text("SELECT count(*) FROM bank_provider_states")
    ).scalar_one()
    if unresolved:
        raise RuntimeError(
            "bank_provider_states contains legacy credentials; create and verify "
            "external secret references before applying this migration"
        )

    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("bank_provider_states") as batch_op:
            if "credential_reference" not in columns:
                batch_op.add_column(
                    sa.Column("credential_reference", sa.String(length=500), nullable=True)
                )
            batch_op.alter_column(
                "credential_reference",
                existing_type=sa.String(length=500),
                nullable=False,
            )
            batch_op.alter_column(
                "access_token_ciphertext",
                existing_type=sa.Text(),
                nullable=True,
            )
    else:
        if "credential_reference" not in columns:
            op.add_column(
                "bank_provider_states",
                sa.Column("credential_reference", sa.String(length=500), nullable=True),
            )
        op.alter_column(
            "bank_provider_states",
            "credential_reference",
            existing_type=sa.String(length=500),
            nullable=False,
        )
        op.alter_column(
            "bank_provider_states",
            "access_token_ciphertext",
            existing_type=sa.Text(),
            nullable=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("bank_provider_states")}
    if "access_token_ciphertext" not in columns:
        return
    new_rows = connection.execute(
        sa.text(
            "SELECT count(*) FROM bank_provider_states "
            "WHERE access_token_ciphertext IS NULL"
        )
    ).scalar_one()
    if new_rows:
        raise RuntimeError(
            "downgrade would strand externally referenced credentials; restore "
            "legacy ciphertexts first or roll back the application only"
        )
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("bank_provider_states") as batch_op:
            batch_op.alter_column(
                "access_token_ciphertext",
                existing_type=sa.Text(),
                nullable=False,
            )
            batch_op.drop_column("credential_reference")
    else:
        op.alter_column(
            "bank_provider_states",
            "access_token_ciphertext",
            existing_type=sa.Text(),
            nullable=False,
        )
        op.drop_column("bank_provider_states", "credential_reference")
