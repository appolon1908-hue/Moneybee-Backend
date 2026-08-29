"""Align finance API replay evidence with the canonical request contract.

Revision ID: 20260827_0016
Revises: 20260826_0015
Create Date: 2026-08-27
"""

from collections.abc import Sequence
import hashlib

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0016"
down_revision: str | None = "20260826_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "journal_entries",
        sa.Column("request_hash", sa.String(length=64), nullable=True),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id FROM journal_entries WHERE request_hash IS NULL")
    ).all()
    for row in rows:
        legacy_hash = hashlib.sha256(f"legacy:{row.id}".encode("utf-8")).hexdigest()
        connection.execute(
            sa.text(
                """
                UPDATE journal_entries
                SET request_hash = :request_hash
                WHERE id = :entry_id
                """
            ),
            {"request_hash": legacy_hash, "entry_id": row.id},
        )

    with op.batch_alter_table("journal_entries") as batch_op:
        batch_op.alter_column(
            "request_hash",
            existing_type=sa.String(length=64),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("journal_entries") as batch_op:
        batch_op.drop_column("request_hash")
