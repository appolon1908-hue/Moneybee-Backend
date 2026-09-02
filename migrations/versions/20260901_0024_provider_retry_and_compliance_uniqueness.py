"""Add durable provider retry state and adverse-notice uniqueness.

Revision ID: 20260901_0024
Revises: 20260901_0023
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0024"
down_revision: str | None = "20260901_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _retry_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("provider_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider_last_error", sa.Text(), nullable=True),
        sa.Column("provider_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_lease_owner", sa.String(length=160), nullable=True),
        sa.Column("provider_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_terminal_at", sa.DateTime(timezone=True), nullable=True),
    )


def upgrade() -> None:
    duplicate_notices = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM ("
            "SELECT underwriting_review_id FROM adverse_action_notices "
            "GROUP BY underwriting_review_id HAVING count(*) > 1"
            ") AS duplicate_reviews"
        )
    ).scalar_one()
    if duplicate_notices:
        raise RuntimeError(
            "duplicate adverse-action notices exist for an underwriting review; "
            "resolve them through an audited data-remediation plan before upgrading"
        )
    for table in ("documents", "contracts"):
        for column in _retry_columns():
            op.add_column(table, column)
        op.create_index(
            f"ix_{table}_provider_next_attempt_at",
            table,
            ["provider_next_attempt_at"],
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("adverse_action_notices") as batch_op:
            batch_op.create_unique_constraint(
                "uq_adverse_action_notice_review", ["underwriting_review_id"]
            )
    else:
        op.create_unique_constraint(
            "uq_adverse_action_notice_review",
            "adverse_action_notices",
            ["underwriting_review_id"],
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT count(*) FROM documents WHERE provider_attempt_count > 0 "
            "OR provider_last_error IS NOT NULL OR provider_next_attempt_at IS NOT NULL "
            "OR provider_lease_owner IS NOT NULL OR provider_terminal_at IS NOT NULL"
        )
    ).scalar_one() or connection.execute(
        sa.text(
            "SELECT count(*) FROM contracts WHERE provider_attempt_count > 0 "
            "OR provider_last_error IS NOT NULL OR provider_next_attempt_at IS NOT NULL "
            "OR provider_lease_owner IS NOT NULL OR provider_terminal_at IS NOT NULL"
        )
    ).scalar_one():
        raise RuntimeError(
            "downgrade would discard provider retry evidence; clear it through an "
            "approved forward-fix procedure first"
        )
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("adverse_action_notices") as batch_op:
            batch_op.drop_constraint("uq_adverse_action_notice_review", type_="unique")
    else:
        op.drop_constraint(
            "uq_adverse_action_notice_review",
            "adverse_action_notices",
            type_="unique",
        )
    for table in ("contracts", "documents"):
        op.drop_index(f"ix_{table}_provider_next_attempt_at", table_name=table)
        with op.batch_alter_table(table) as batch_op:
            for name in (
                "provider_terminal_at",
                "provider_lease_expires_at",
                "provider_lease_owner",
                "provider_next_attempt_at",
                "provider_last_error",
                "provider_attempt_count",
            ):
                batch_op.drop_column(name)
