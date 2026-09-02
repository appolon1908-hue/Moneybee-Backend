"""Bind document evidence to immutable object-storage versions.

Revision ID: 20260902_0028
Revises: 20260902_0027
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260902_0028"
down_revision: str | None = "20260902_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("storage_version_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    protected = bind.execute(
        sa.text("SELECT 1 FROM documents WHERE storage_version_id IS NOT NULL LIMIT 1")
    ).first()
    if protected is not None:
        raise RuntimeError("Downgrade would discard immutable document-version evidence")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("storage_version_id")
