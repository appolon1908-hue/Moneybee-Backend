from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import Record


class PortalTask(Base, Record):
    __tablename__ = "portal_tasks"

    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assignee_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="OPEN", index=True)
    priority: Mapped[str] = mapped_column(String(30), default="NORMAL", index=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PortalNotification(Base, Record):
    __tablename__ = "portal_notifications"

    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    action_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PortalConversation(Base, Record):
    __tablename__ = "portal_conversations"

    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    topic: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="OPEN", index=True)
    created_by_subject: Mapped[str] = mapped_column(String(255), index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PortalConversationParticipant(Base, Record):
    __tablename__ = "portal_conversation_participants"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "subject",
            name="uq_portal_conversation_participant",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_conversations.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(255), index=True)
    participant_type: Mapped[str] = mapped_column(String(40), index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PortalMessage(Base, Record):
    __tablename__ = "portal_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_conversations.id", ondelete="CASCADE"), index=True
    )
    sender_subject: Mapped[str] = mapped_column(String(255), index=True)
    sender_type: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(40), default="TEXT")
    attachment_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class DocumentUploadSession(Base, Record):
    __tablename__ = "document_upload_sessions"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_document_upload_session_storage_key"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    created_by_subject: Mapped[str] = mapped_column(String(255), index=True)
    document_type: Mapped[str] = mapped_column(String(100), index=True)
    original_file_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int]
    expected_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(40), default="CREATED", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)
