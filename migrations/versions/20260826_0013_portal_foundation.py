"""Add shared portal foundation tables.

Revision ID: 20260826_0013
Revises: 20260823_0012
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0013"
down_revision: str | None = "20260823_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portal_tasks",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("assigned_to_subject", sa.String(length=255), nullable=True),
        sa.Column("created_by_subject", sa.String(length=255), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portal_tasks_tenant_id", "portal_tasks", ["tenant_id"])
    op.create_index(
        "ix_portal_tasks_application_id", "portal_tasks", ["application_id"]
    )
    op.create_index("ix_portal_tasks_status", "portal_tasks", ["status"])
    op.create_index("ix_portal_tasks_priority", "portal_tasks", ["priority"])
    op.create_index(
        "ix_portal_tasks_assigned_to_subject",
        "portal_tasks",
        ["assigned_to_subject"],
    )
    op.create_index(
        "ix_portal_tasks_created_by_subject",
        "portal_tasks",
        ["created_by_subject"],
    )
    op.create_index(
        "ix_portal_tasks_tenant_status_due",
        "portal_tasks",
        ["tenant_id", "status", "due_at"],
    )
    op.create_index(
        "ix_portal_tasks_assignee_status",
        "portal_tasks",
        ["assigned_to_subject", "status"],
    )

    op.create_table(
        "portal_notifications",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_subject", sa.String(length=255), nullable=False),
        sa.Column("notification_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("href", sa.String(length=1000), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portal_notifications_tenant_id",
        "portal_notifications",
        ["tenant_id"],
    )
    op.create_index(
        "ix_portal_notifications_recipient_subject",
        "portal_notifications",
        ["recipient_subject"],
    )
    op.create_index(
        "ix_portal_notifications_recipient_created",
        "portal_notifications",
        ["recipient_subject", "created_at"],
    )

    op.create_table(
        "portal_conversations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("topic", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_by_subject", sa.String(length=255), nullable=False),
        sa.Column("participant_subjects", sa.JSON(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portal_conversations_tenant_id",
        "portal_conversations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_portal_conversations_application_id",
        "portal_conversations",
        ["application_id"],
    )
    op.create_index(
        "ix_portal_conversations_status", "portal_conversations", ["status"]
    )
    op.create_index(
        "ix_portal_conversations_created_by_subject",
        "portal_conversations",
        ["created_by_subject"],
    )
    op.create_index(
        "ix_portal_conversations_last_message_at",
        "portal_conversations",
        ["last_message_at"],
    )
    op.create_index(
        "ix_portal_conversations_tenant_last_message",
        "portal_conversations",
        ["tenant_id", "last_message_at"],
    )

    op.create_table(
        "portal_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sender_subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["portal_conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portal_messages_conversation_id",
        "portal_messages",
        ["conversation_id"],
    )
    op.create_index(
        "ix_portal_messages_sender_subject",
        "portal_messages",
        ["sender_subject"],
    )
    op.create_index(
        "ix_portal_messages_conversation_created",
        "portal_messages",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "portal_upload_sessions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("condition_id", sa.Uuid(), nullable=True),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("original_file_name", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_by_subject", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_etag", sa.String(length=255), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["condition_id"],
            ["underwriting_conditions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "storage_key", name="uq_portal_upload_session_storage_key"
        ),
    )
    op.create_index(
        "ix_portal_upload_sessions_tenant_id",
        "portal_upload_sessions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_portal_upload_sessions_application_id",
        "portal_upload_sessions",
        ["application_id"],
    )
    op.create_index(
        "ix_portal_upload_sessions_status",
        "portal_upload_sessions",
        ["status"],
    )
    op.create_index(
        "ix_portal_upload_sessions_created_by_subject",
        "portal_upload_sessions",
        ["created_by_subject"],
    )
    op.create_index(
        "ix_portal_upload_sessions_expires_at",
        "portal_upload_sessions",
        ["expires_at"],
    )
    op.create_index(
        "ix_portal_upload_sessions_application_status",
        "portal_upload_sessions",
        ["application_id", "status"],
    )
    op.create_index(
        "ix_portal_upload_sessions_tenant_creator",
        "portal_upload_sessions",
        ["tenant_id", "created_by_subject"],
    )


def downgrade() -> None:
    op.drop_table("portal_upload_sessions")
    op.drop_table("portal_messages")
    op.drop_table("portal_conversations")
    op.drop_table("portal_notifications")
    op.drop_table("portal_tasks")
