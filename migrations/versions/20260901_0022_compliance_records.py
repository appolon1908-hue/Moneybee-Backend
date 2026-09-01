"""Add adverse-action notice, commercial-financing disclosure, and
commission tax-record tables.

Revision ID: 20260901_0022
Revises: 20260901_0021
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0022"
down_revision: str | None = "20260901_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "adverse_action_notices",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("underwriting_review_id", sa.Uuid(), nullable=False),
        sa.Column("lender_id", sa.Uuid(), nullable=False),
        sa.Column("creditor_name", sa.String(length=255), nullable=False),
        sa.Column("principal_reasons", sa.JSON(), nullable=False),
        sa.Column("notice_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="GENERATED", nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        *record_columns(),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["submission_id"], ["lender_submissions.id"]),
        sa.ForeignKeyConstraint(["underwriting_review_id"], ["underwriting_reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("application_id", "submission_id", "underwriting_review_id"):
        op.create_index(f"ix_adverse_action_notices_{column}", "adverse_action_notices", [column])

    op.create_table(
        "commercial_financing_disclosures",
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=2), nullable=True),
        sa.Column("amount_financed", sa.Numeric(18, 2), nullable=False),
        sa.Column("finance_charge", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_repayment_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("estimated_apr", sa.Numeric(9, 4), nullable=True),
        sa.Column("payment_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("payment_frequency", sa.String(length=40), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("prepayment_policy", sa.Text(), nullable=False),
        sa.Column("disclosure_text", sa.Text(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=255), nullable=True),
        *record_columns(),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"]),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offer_id", name="uq_commercial_financing_disclosure_offer"),
    )
    op.create_index(
        "ix_commercial_financing_disclosures_application_id",
        "commercial_financing_disclosures",
        ["application_id"],
    )

    op.create_table(
        "commission_tax_records",
        sa.Column("recipient_type", sa.String(length=50), nullable=False),
        sa.Column("recipient_reference", sa.String(length=255), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
        sa.Column("tin_ciphertext", sa.String(length=500), nullable=True),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("commission_count", sa.Integer(), nullable=False),
        sa.Column("requires_1099", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filing_reference", sa.String(length=255), nullable=True),
        *record_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipient_reference", "tax_year", name="uq_commission_tax_record_recipient_year"
        ),
    )
    op.create_index(
        "ix_commission_tax_records_recipient_reference",
        "commission_tax_records",
        ["recipient_reference"],
    )
    op.create_index("ix_commission_tax_records_tax_year", "commission_tax_records", ["tax_year"])


def downgrade() -> None:
    op.drop_table("commission_tax_records")
    op.drop_table("commercial_financing_disclosures")
    op.drop_table("adverse_action_notices")
