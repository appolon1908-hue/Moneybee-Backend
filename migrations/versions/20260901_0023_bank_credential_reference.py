"""Stage bank-provider credentials behind an external secret reference.

Revision ID: 20260901_0023
Revises: 20260901_0022a
Create Date: 2026-09-01

The legacy encrypted column is intentionally retained during the compatibility
window. The application does not read or write it after this migration.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0023"
down_revision: str | None = "20260901_0022a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("bank_provider_states")}
    if "credential_reference" not in columns:
        raise RuntimeError(
            "upgrade to 20260901_0022a and populate verified external references first"
        )
    unresolved = connection.execute(
        sa.text(
            "SELECT count(*) FROM bank_provider_states "
            "WHERE credential_reference IS NULL "
            "OR trim(credential_reference) NOT LIKE 'secret://%'"
        )
    ).scalar_one()
    if unresolved:
        raise RuntimeError(
            "bank_provider_states contains unresolved credentials; stop at revision "
            "20260901_0022a and populate verified secret:// references before retrying"
        )
    if "access_token_ciphertext" not in columns:
        return

    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("bank_provider_states") as batch_op:
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
                "credential_reference",
                existing_type=sa.String(length=500),
                nullable=True,
            )
            batch_op.alter_column(
                "access_token_ciphertext",
                existing_type=sa.Text(),
                nullable=False,
            )
    else:
        op.alter_column(
            "bank_provider_states",
            "credential_reference",
            existing_type=sa.String(length=500),
            nullable=True,
        )
        op.alter_column(
            "bank_provider_states",
            "access_token_ciphertext",
            existing_type=sa.Text(),
            nullable=False,
        )
