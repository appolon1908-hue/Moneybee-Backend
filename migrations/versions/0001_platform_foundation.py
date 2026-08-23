"""platform foundation

Revision ID: 0001_platform_foundation
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_platform_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_flags",
        sa.Column("key", sa.String(length=150), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    capability = sa.table(
        "capability_flags",
        sa.column("key", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("risk_level", sa.String),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(
        capability,
        [
            {"key": "credit.live_pull", "enabled": False, "risk_level": "FINANCIAL_CRITICAL", "description": "Live commercial credit requests"},
            {"key": "lenders.live_submission", "enabled": False, "risk_level": "FINANCIAL_CRITICAL", "description": "Live lender submissions"},
            {"key": "esign.live_send", "enabled": False, "risk_level": "FINANCIAL_CRITICAL", "description": "Live e-signature delivery"},
            {"key": "funding.live_confirmation", "enabled": False, "risk_level": "FINANCIAL_CRITICAL", "description": "Live funding confirmation"},
            {"key": "payments", "enabled": False, "risk_level": "FINANCIAL_CRITICAL", "description": "Customer payment capability"},
            {"key": "payouts", "enabled": False, "risk_level": "FINANCIAL_CRITICAL", "description": "Outbound payout capability"},
        ],
    )
    op.create_table(
        "readiness_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("gate", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_sha", sa.String(length=128), nullable=False),
        sa.Column("environment", sa.String(length=40), nullable=False),
        sa.Column("evidence_type", sa.String(length=100), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(length=255)),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_readiness_evidence_gate", "readiness_evidence", ["gate"])


def downgrade() -> None:
    op.drop_index("ix_readiness_evidence_gate", table_name="readiness_evidence")
    op.drop_table("readiness_evidence")
    op.drop_table("capability_flags")
