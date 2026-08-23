"""Expand the application lifecycle enum.

Revision ID: 20260823_0006
Revises: 20260823_0005
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260823_0006"
down_revision: str | None = "20260823_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALUES = (
    "APPLICATION_COMPLETE",
    "VERIFICATION_PENDING",
    "SUBMITTED_TO_LENDERS",
    "UNDERWRITING",
    "CONDITIONS_PENDING",
    "CONDITIONS_COMPLETE",
    "CONTRACT_READY",
    "CONTRACT_SENT",
    "CONTRACT_SIGNED",
    "APPROVED_FOR_FUNDING",
    "FUNDS_SENT",
    "CLOSED",
    "COMPLIANCE_REVIEW",
    "DECLINED",
    "EXPIRED",
    "CANCELLED",
)


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for value in VALUES:
            op.execute(
                f"ALTER TYPE applicationstatus ADD VALUE IF NOT EXISTS '{value}'"
            )


def downgrade() -> None:
    # PostgreSQL enum labels cannot be safely removed while rows may use them.
    # The lifecycle expansion is intentionally additive.
    pass
