"""Add idempotent lender portal decision records.

Revision ID: 20260826_0014
Revises: 20260826_0013
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0014"
down_revision: str | None = "20260826_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lender_portal_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("lender_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("decision_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["lender_id"], ["lenders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["lender_submissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lender_id",
            "submission_id",
            "idempotency_key",
            name="uq_lender_portal_decision_command",
        ),
    )
    op.create_index(
        "ix_lender_portal_decisions_organization_id",
        "lender_portal_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_lender_portal_decisions_lender_id",
        "lender_portal_decisions",
        ["lender_id"],
    )
    op.create_index(
        "ix_lender_portal_decisions_submission_id",
        "lender_portal_decisions",
        ["submission_id"],
    )
    op.create_index(
        "ix_lender_portal_decisions_created_by_user_id",
        "lender_portal_decisions",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_lender_portal_decisions_decision",
        "lender_portal_decisions",
        ["decision"],
    )
    op.create_index(
        "ix_lender_portal_decisions_status",
        "lender_portal_decisions",
        ["status"],
    )
    op.create_index(
        "ix_lender_portal_decisions_created_at",
        "lender_portal_decisions",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lender_portal_decisions_created_at",
        table_name="lender_portal_decisions",
    )
    op.drop_index(
        "ix_lender_portal_decisions_status",
        table_name="lender_portal_decisions",
    )
    op.drop_index(
        "ix_lender_portal_decisions_decision",
        table_name="lender_portal_decisions",
    )
    op.drop_index(
        "ix_lender_portal_decisions_created_by_user_id",
        table_name="lender_portal_decisions",
    )
    op.drop_index(
        "ix_lender_portal_decisions_submission_id",
        table_name="lender_portal_decisions",
    )
    op.drop_index(
        "ix_lender_portal_decisions_lender_id",
        table_name="lender_portal_decisions",
    )
    op.drop_index(
        "ix_lender_portal_decisions_organization_id",
        table_name="lender_portal_decisions",
    )
    op.drop_table("lender_portal_decisions")
