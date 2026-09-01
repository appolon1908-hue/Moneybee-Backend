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
    columns = {
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'bank_provider_states'"
            )
        )
    }
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
    columns = {
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'bank_provider_states'"
            )
        )
    }
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
    op.alter_column(
        "bank_provider_states",
        "access_token_ciphertext",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.drop_column("bank_provider_states", "credential_reference")
