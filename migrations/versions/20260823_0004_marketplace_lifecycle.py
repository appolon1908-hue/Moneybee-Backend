"""Add marketplace lifecycle and integration state.

Revision ID: 20260823_0004
Revises: 20260823_0003
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260823_0004"
down_revision: str | None = "20260823_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    ]


def application_table(
    name: str,
    *columns: sa.Column,
    unique: bool = False,
    foreign_keys: tuple[tuple[str, str], ...] = (),
) -> None:
    constraints: list = [
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
    ]
    constraints.extend(
        sa.ForeignKeyConstraint([local], [target])
        for local, target in foreign_keys
    )
    if unique:
        constraints.append(sa.UniqueConstraint("application_id"))
    op.create_table(
        name,
        sa.Column("application_id", sa.Uuid(), nullable=False),
        *columns,
        *constraints,
        *record_columns(),
    )
    op.create_index(f"ix_{name}_application_id", name, ["application_id"])


def upgrade() -> None:
    application_table(
        "bank_connections",
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
    )
    application_table(
        "bank_analyses",
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("average_monthly_deposits", sa.Numeric(18, 2), nullable=True),
        sa.Column("average_daily_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("negative_balance_days_90d", sa.Integer(), nullable=False),
        sa.Column("nsf_count_90d", sa.Integer(), nullable=False),
        sa.Column("deposit_count_90d", sa.Integer(), nullable=False),
        sa.Column("largest_deposit_90d", sa.Numeric(18, 2), nullable=True),
        sa.Column("existing_payment_obligations", sa.Numeric(18, 2), nullable=True),
        sa.Column("revenue_trend", sa.String(40), nullable=True),
        sa.Column("cash_flow_trend", sa.String(40), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
    )
    application_table(
        "verifications",
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("verification_type", sa.String(60), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("normalized_result", sa.JSON(), nullable=False),
        foreign_keys=(("owner_id", "owners.id"),),
    )
    application_table(
        "credit_authorizations",
        sa.Column("authorization_version", sa.String(50), nullable=False),
        sa.Column("document_hash", sa.String(128), nullable=False),
        sa.Column("accepted_by", sa.String(200), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint(
        "uq_credit_authorization_version",
        "credit_authorizations",
        ["application_id", "authorization_version"],
    )
    application_table(
        "credit_results",
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("normalized_result", sa.JSON(), nullable=False),
    )
    application_table(
        "fraud_assessments",
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
    )

    op.create_table(
        "lender_submissions",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("lender_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("program_version", sa.Integer(), nullable=False),
        sa.Column("external_submission_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(60), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["program_id"], ["lender_programs.id"]),
        sa.UniqueConstraint(
            "application_id",
            "program_id",
            "program_version",
            name="uq_submission_application_program_version",
        ),
        *record_columns(),
    )
    op.create_index(
        "ix_lender_submissions_application_id",
        "lender_submissions",
        ["application_id"],
    )
    op.create_index(
        "ix_lender_submissions_lender_id",
        "lender_submissions",
        ["lender_id"],
    )

    op.create_table(
        "underwriting_conditions",
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(60), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["lender_submissions.id"]),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        *record_columns(),
    )
    op.create_index(
        "ix_underwriting_conditions_submission_id",
        "underwriting_conditions",
        ["submission_id"],
    )
    op.create_index(
        "ix_underwriting_conditions_application_id",
        "underwriting_conditions",
        ["application_id"],
    )

    op.create_table(
        "documents",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("condition_id", sa.Uuid(), nullable=True),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("original_file_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(1000), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("uploaded_by", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"]),
        sa.ForeignKeyConstraint(["condition_id"], ["underwriting_conditions.id"]),
        *record_columns(),
    )
    op.create_index("ix_documents_application_id", "documents", ["application_id"])

    application_table(
        "contracts",
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("template_version", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(100), nullable=True),
        sa.Column("external_envelope_id", sa.String(255), nullable=True),
        sa.Column("document_hash", sa.String(128), nullable=True),
        sa.Column("status", sa.String(60), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        foreign_keys=(("offer_id", "offers.id"),),
    )

    application_table(
        "fundings",
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(60), nullable=False),
        sa.Column("approved_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("funded_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("funds_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("funding_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        unique=True,
        foreign_keys=(("offer_id", "offers.id"),),
    )
    op.create_unique_constraint("uq_fundings_offer_id", "fundings", ["offer_id"])

    op.create_table(
        "commissions",
        sa.Column("funding_id", sa.Uuid(), nullable=False),
        sa.Column("expected_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("received_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["funding_id"], ["fundings.id"]),
        sa.UniqueConstraint("funding_id"),
        *record_columns(),
    )
    op.create_index("ix_commissions_funding_id", "commissions", ["funding_id"])

    op.create_table(
        "renewal_opportunities",
        sa.Column("original_funding_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("eligible_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligibility_status", sa.String(40), nullable=False),
        sa.Column("estimated_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["original_funding_id"], ["fundings.id"]),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.UniqueConstraint("original_funding_id"),
        *record_columns(),
    )
    op.create_index(
        "ix_renewal_opportunities_original_funding_id",
        "renewal_opportunities",
        ["original_funding_id"],
    )
    op.create_index(
        "ix_renewal_opportunities_application_id",
        "renewal_opportunities",
        ["application_id"],
    )

    op.create_table(
        "complaints",
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(30), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        *record_columns(),
    )
    op.create_index("ix_complaints_application_id", "complaints", ["application_id"])
    op.create_index("ix_complaints_created_by", "complaints", ["created_by"])

    op.create_table(
        "affiliates",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tracking_code", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("tracking_code"),
        *record_columns(),
    )
    op.create_index("ix_affiliates_tracking_code", "affiliates", ["tracking_code"])

    op.create_table(
        "communications",
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("recipient_reference", sa.String(320), nullable=False),
        sa.Column("template_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        *record_columns(),
    )
    op.create_index(
        "ix_communications_application_id",
        "communications",
        ["application_id"],
    )

    op.create_table(
        "integration_events",
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("response", sa.JSON(), nullable=False),
        *record_columns(),
    )
    op.create_index("ix_integration_events_provider", "integration_events", ["provider"])
    op.create_index(
        "ix_integration_events_aggregate_id",
        "integration_events",
        ["aggregate_id"],
    )
    op.create_index("ix_integration_events_status", "integration_events", ["status"])

    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("route", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(128), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "actor_id",
            "route",
            "key",
            name="uq_idempotency_actor_route_key",
        ),
        *record_columns(),
    )
    op.create_index("ix_idempotency_keys_key", "idempotency_keys", ["key"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_key", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_index("ix_integration_events_status", table_name="integration_events")
    op.drop_index("ix_integration_events_aggregate_id", table_name="integration_events")
    op.drop_index("ix_integration_events_provider", table_name="integration_events")
    op.drop_table("integration_events")
    op.drop_index("ix_communications_application_id", table_name="communications")
    op.drop_table("communications")
    op.drop_index("ix_affiliates_tracking_code", table_name="affiliates")
    op.drop_table("affiliates")
    op.drop_index("ix_complaints_created_by", table_name="complaints")
    op.drop_index("ix_complaints_application_id", table_name="complaints")
    op.drop_table("complaints")
    op.drop_index(
        "ix_renewal_opportunities_application_id",
        table_name="renewal_opportunities",
    )
    op.drop_index(
        "ix_renewal_opportunities_original_funding_id",
        table_name="renewal_opportunities",
    )
    op.drop_table("renewal_opportunities")
    op.drop_index("ix_commissions_funding_id", table_name="commissions")
    op.drop_table("commissions")
    op.drop_index("ix_fundings_application_id", table_name="fundings")
    op.drop_table("fundings")
    op.drop_index("ix_contracts_application_id", table_name="contracts")
    op.drop_table("contracts")
    op.drop_index("ix_documents_application_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index(
        "ix_underwriting_conditions_application_id",
        table_name="underwriting_conditions",
    )
    op.drop_index(
        "ix_underwriting_conditions_submission_id",
        table_name="underwriting_conditions",
    )
    op.drop_table("underwriting_conditions")
    op.drop_index("ix_lender_submissions_lender_id", table_name="lender_submissions")
    op.drop_index(
        "ix_lender_submissions_application_id",
        table_name="lender_submissions",
    )
    op.drop_table("lender_submissions")
    for table in [
        "fraud_assessments",
        "credit_results",
        "credit_authorizations",
        "verifications",
        "bank_analyses",
        "bank_connections",
    ]:
        op.drop_index(f"ix_{table}_application_id", table_name=table)
        op.drop_table(table)
