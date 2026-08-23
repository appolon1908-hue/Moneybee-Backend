"""Add fail-closed capability flags and provider readiness.

Revision ID: 20260823_0002
Revises: 20260823_0001
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260823_0002"
down_revision: str | None = "20260823_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

provider_status = sa.Enum(
    "NOT_CONFIGURED",
    "CONFIGURED",
    "VERIFYING",
    "READY",
    "DEGRADED",
    "DISABLED",
    name="providerstatus",
)

DEFAULT_CAPABILITIES = (
    ("crm.write", "crm"),
    ("bank.live_connection", "bank"),
    ("kyb.live_verification", "kyb"),
    ("credit.live_pull", "credit"),
    ("lenders.live_submission", "lender"),
    ("esign.live_send", "esign"),
    ("communications.live_email", "email"),
    ("communications.live_sms", "sms"),
    ("funding.live_confirmation", None),
    ("matching.auto_submit", "lender"),
    ("adverse_action.live_delivery", "communications"),
)


def upgrade() -> None:
    capability_flags = op.create_table(
        "capability_flags",
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("environment", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled_by", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_capability_flags_key", "capability_flags", ["key"])
    op.create_index("ix_capability_flags_environment", "capability_flags", ["environment"])

    op.create_table(
        "provider_connections",
        sa.Column("provider_type", sa.String(length=80), nullable=False),
        sa.Column("provider_name", sa.String(length=120), nullable=False),
        sa.Column("environment", sa.String(length=40), nullable=False),
        sa.Column("status", provider_status, server_default="NOT_CONFIGURED", nullable=False),
        sa.Column("external_account_id", sa.String(length=200), nullable=True),
        sa.Column("configuration_metadata", sa.JSON(), nullable=False),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_type",
            "provider_name",
            "environment",
            name="uq_provider_connection_identity",
        ),
    )
    op.create_index(
        "ix_provider_connections_provider_type",
        "provider_connections",
        ["provider_type"],
    )
    op.create_index(
        "ix_provider_connections_provider_name",
        "provider_connections",
        ["provider_name"],
    )
    op.create_index(
        "ix_provider_connections_environment",
        "provider_connections",
        ["environment"],
    )

    op.bulk_insert(
        capability_flags,
        [
            {
                "id": __import__("uuid").uuid4(),
                "key": key,
                "environment": "production",
                "enabled": False,
                "provider": provider,
                "reason": "Disabled by default; requires authorized production activation.",
            }
            for key, provider in DEFAULT_CAPABILITIES
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_provider_connections_environment", table_name="provider_connections")
    op.drop_index("ix_provider_connections_provider_name", table_name="provider_connections")
    op.drop_index("ix_provider_connections_provider_type", table_name="provider_connections")
    op.drop_table("provider_connections")
    op.drop_index("ix_capability_flags_environment", table_name="capability_flags")
    op.drop_index("ix_capability_flags_key", table_name="capability_flags")
    op.drop_table("capability_flags")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        provider_status.drop(bind, checkfirst=True)
