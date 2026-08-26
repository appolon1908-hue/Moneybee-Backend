"""Add secure portal task, notification, messaging, and upload-session records.

Revision ID: 20260826_0013
Revises: 20260823_0012
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_0013"
down_revision: str | None = "20260823_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "portal_tasks",
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_subject", sa.String(length=255), nullable=True),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), server_default="OPEN", nullable=False),
        sa.Column("priority", sa.String(length=30), server_default="NORMAL", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_type", sa.String(length=100), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        *record_columns(),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "application_id",
        "organization_id",
        "assignee_user_id",
        "assignee_subject",
        "task_type",
        "status",
        "priority",
        "due_at",
    ):
        op.create_index(f"ix_portal_tasks_{column}", "portal_tasks", [column])

    op.create_table(
        "portal_notifications",
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("action_path", sa.String(length=500), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        *record_columns(),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "application_id",
        "organization_id",
        "user_id",
        "subject",
        "category",
        "read_at",
    ):
        op.create_index(
            f"ix_portal_notifications_{column}", "portal_notifications", [column]
        )

    op.create_table(
        "portal_conversations",
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="OPEN", nullable=False),
        sa.Column("created_by_subject", sa.String(length=255), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        *record_columns(),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "application_id",
        "organization_id",
        "status",
        "created_by_subject",
        "last_message_at",
    ):
        op.create_index(
            f"ix_portal_conversations_{column}", "portal_conversations", [column]
        )

    op.create_table(
        "portal_conversation_participants",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("participant_type", sa.String(length=40), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        *record_columns(),
        sa.ForeignKeyConstraint(["conversation_id"], ["portal_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "subject", name="uq_portal_conversation_participant"),
    )
    for column in ("conversation_id", "subject", "participant_type", "organization_id"):
        op.create_index(
            f"ix_portal_conversation_participants_{column}",
            "portal_conversation_participants",
            [column],
        )

    op.create_table(
        "portal_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sender_subject", sa.String(length=255), nullable=False),
        sa.Column("sender_type", sa.String(length=40), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("message_type", sa.String(length=40), server_default="TEXT", nullable=False),
        sa.Column("attachment_document_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        *record_columns(),
        sa.ForeignKeyConstraint(["conversation_id"], ["portal_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attachment_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("conversation_id", "sender_subject"):
        op.create_index(f"ix_portal_messages_{column}", "portal_messages", [column])

    op.create_table(
        "document_upload_sessions",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_subject", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=100), nullable=False),
        sa.Column("original_file_name", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("expected_sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="CREATED", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        *record_columns(),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_document_upload_session_storage_key"),
    )
    for column in (
        "application_id",
        "created_by_subject",
        "document_type",
        "status",
        "expires_at",
    ):
        op.create_index(
            f"ix_document_upload_sessions_{column}",
            "document_upload_sessions",
            [column],
        )


def downgrade() -> None:
    for table, columns in (
        (
            "document_upload_sessions",
            ("application_id", "created_by_subject", "document_type", "status", "expires_at"),
        ),
        ("portal_messages", ("conversation_id", "sender_subject")),
        (
            "portal_conversation_participants",
            ("conversation_id", "subject", "participant_type", "organization_id"),
        ),
        (
            "portal_conversations",
            ("application_id", "organization_id", "status", "created_by_subject", "last_message_at"),
        ),
        (
            "portal_notifications",
            ("application_id", "organization_id", "user_id", "subject", "category", "read_at"),
        ),
        (
            "portal_tasks",
            ("application_id", "organization_id", "assignee_user_id", "assignee_subject", "task_type", "status", "priority", "due_at"),
        ),
    ):
        for column in reversed(columns):
            op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_table(table)
