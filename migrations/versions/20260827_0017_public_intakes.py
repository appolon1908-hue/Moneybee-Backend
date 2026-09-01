"""Add public intake and consent evidence records.

Revision ID: 20260827_0017
Revises: 20260827_0016
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0017"
down_revision: str | None = "20260827_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "public_intakes",
        sa.Column("intake_type", sa.String(length=80), nullable=False),
        sa.Column("reference", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="RECEIVED", nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("business_name", sa.String(length=240), nullable=True),
        sa.Column("subject", sa.String(length=240), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("attribution", sa.JSON(), nullable=False),
        sa.Column("source_evidence", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference", name="uq_public_intake_reference"),
    )
    for column in ("intake_type", "reference", "status", "email", "phone", "business_name"):
        op.create_index(f"ix_public_intakes_{column}", "public_intakes", [column])

    op.create_table(
        "public_intake_consents",
        sa.Column("public_intake_id", sa.Uuid(), nullable=False),
        sa.Column("consent_type", sa.String(length=100), nullable=False),
        sa.Column("document_version", sa.String(length=80), nullable=False),
        sa.Column("document_hash", sa.String(length=64), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["public_intake_id"],
            ["public_intakes.id"],
            name="fk_public_intake_consents_intake",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_public_intake_consents_public_intake_id",
        "public_intake_consents",
        ["public_intake_id"],
    )
    op.create_index(
        "ix_public_intake_consents_consent_type",
        "public_intake_consents",
        ["consent_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_public_intake_consents_consent_type", table_name="public_intake_consents")
    op.drop_index(
        "ix_public_intake_consents_public_intake_id",
        table_name="public_intake_consents",
    )
    op.drop_table("public_intake_consents")
    for column in reversed(("intake_type", "reference", "status", "email", "phone", "business_name")):
        op.drop_index(f"ix_public_intakes_{column}", table_name="public_intakes")
    op.drop_table("public_intakes")
