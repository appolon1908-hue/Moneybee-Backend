"""Create the initial MoneyBee system-of-record tables.

Revision ID: 20260823_0001
Revises:
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260823_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

lead_status = sa.Enum(
    "NEW",
    "APPLICATION_STARTED",
    "MATCHING",
    "OFFERED",
    "FUNDED",
    "DUPLICATE",
    "FRAUD_REVIEW",
    "LOST",
    name="leadstatus",
)
application_status = sa.Enum(
    "APPLICATION_STARTED",
    "APPLICATION_IN_PROGRESS",
    "READY_FOR_MATCHING",
    "MATCHED",
    "OFFERS_AVAILABLE",
    "OFFER_ACCEPTED",
    "FUNDED",
    "WITHDRAWN",
    "FRAUD_REVIEW",
    name="applicationstatus",
)
outbox_status = sa.Enum(
    "PENDING",
    "LEASED",
    "DELIVERED",
    "RETRY",
    "DEAD",
    name="outboxstatus",
)


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("business_name", sa.String(length=240), nullable=False),
        sa.Column("funding_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("monthly_revenue", sa.Numeric(18, 2), nullable=False),
        sa.Column("use_of_funds", sa.String(length=80), nullable=False),
        sa.Column("time_in_business_months", sa.Integer(), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("status", lead_status, server_default="NEW", nullable=False),
        sa.Column("attribution", sa.JSON(), nullable=False),
        *record_columns(),
    )
    op.create_index("ix_leads_email", "leads", ["email"])
    op.create_index("ix_leads_phone", "leads", ["phone"])
    op.create_index("ix_leads_business_name", "leads", ["business_name"])

    op.create_table(
        "applications",
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("requested_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("monthly_revenue", sa.Numeric(18, 2), nullable=False),
        sa.Column("time_in_business_months", sa.Integer(), nullable=False),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=True),
        sa.Column(
            "status",
            application_status,
            server_default="APPLICATION_STARTED",
            nullable=False,
        ),
        sa.Column("completion_percentage", sa.Integer(), server_default="20", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.UniqueConstraint("lead_id"),
        *record_columns(),
    )

    op.create_table(
        "consents",
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("consent_type", sa.String(length=100), nullable=False),
        sa.Column("document_version", sa.String(length=80), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        *record_columns(),
    )

    op.create_table(
        "lender_programs",
        sa.Column("lender_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("product_type", sa.String(length=80), nullable=False),
        sa.Column("min_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("max_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("minimum_monthly_revenue", sa.Numeric(18, 2), nullable=False),
        sa.Column("minimum_time_in_business_months", sa.Integer(), nullable=False),
        sa.Column("states", sa.JSON(), nullable=False),
        sa.Column("excluded_industries", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *record_columns(),
    )
    op.create_index("ix_lender_programs_lender_id", "lender_programs", ["lender_id"])

    op.create_table(
        "application_matches",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("lender_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("program_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["program_id"], ["lender_programs.id"]),
        *record_columns(),
    )
    op.create_index(
        "ix_application_matches_application_id",
        "application_matches",
        ["application_id"],
    )

    op.create_table(
        "offers",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("lender_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=True),
        sa.Column("product_type", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("payment_frequency", sa.String(length=40), nullable=False),
        sa.Column("payment_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("apr", sa.Numeric(8, 4), nullable=True),
        sa.Column("factor_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("origination_fee", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("total_repayment", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(length=40), server_default="AVAILABLE", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["program_id"], ["lender_programs.id"]),
        *record_columns(),
    )
    op.create_index("ix_offers_application_id", "offers", ["application_id"])

    op.create_table(
        "outbox_events",
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", outbox_status, server_default="PENDING", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("idempotency_key"),
        *record_columns(),
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])

    op.create_table(
        "audit_events",
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=120), nullable=False),
        sa.Column("request_id", sa.String(length=120), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        *record_columns(),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_outbox_events_event_type", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_offers_application_id", table_name="offers")
    op.drop_table("offers")
    op.drop_index("ix_application_matches_application_id", table_name="application_matches")
    op.drop_table("application_matches")
    op.drop_index("ix_lender_programs_lender_id", table_name="lender_programs")
    op.drop_table("lender_programs")
    op.drop_table("consents")
    op.drop_table("applications")
    op.drop_index("ix_leads_business_name", table_name="leads")
    op.drop_index("ix_leads_phone", table_name="leads")
    op.drop_index("ix_leads_email", table_name="leads")
    op.drop_table("leads")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        outbox_status.drop(bind, checkfirst=True)
        application_status.drop(bind, checkfirst=True)
        lead_status.drop(bind, checkfirst=True)
