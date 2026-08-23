"""bootstrap platform metadata

Revision ID: 0001_bootstrap
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_bootstrap"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "platform_metadata",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table("platform_metadata")
