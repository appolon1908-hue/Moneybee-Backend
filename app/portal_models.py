import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class PortalRecord:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PortalTask(Base, PortalRecord):
    __tablename__ = "portal_tasks"
    __table_args__ = (
        Index("ix_portal_tasks_tenant_status_due", "tenant_id", "status", "due_at"),
        Index("ix_portal_tasks_assignee_status", "assigned_to_subject", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column(String(80), default="GENERAL")
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="OPEN", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL", index=True)
    assigned_to_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    created_by_subject: Mapped[str] = mapped_column(String(255), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PortalNotification(Base, PortalRecord):
    __tablename__ = "portal_notifications"
    __table_args__ = (
        Index(
            "ix_portal_notifications_recipient_created",
            "recipient_subject",
            "created_at",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    recipient_subject: Mapped[str] = mapped_column(String(255), index=True)
    notification_type: Mapped[str] = mapped_column(String(80), default="GENERAL")
    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text)
    href: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PortalConversation(Base, PortalRecord):
    __tablename__ = "portal_conversations"
    __table_args__ = (
        Index(
            "ix_portal_conversations_tenant_last_message",
            "tenant_id",
            "last_message_at",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    topic: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(40), default="OPEN", index=True)
    created_by_subject: Mapped[str] = mapped_column(String(255), index=True)
    participant_subjects: Mapped[list] = mapped_column(JSON, default=list)
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PortalMessage(Base, PortalRecord):
    __tablename__ = "portal_messages"
    __table_args__ = (
        Index(
            "ix_portal_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portal_conversations.id", ondelete="CASCADE"), index=True
    )
    sender_subject: Mapped[str] = mapped_column(String(255), index=True)
    body: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PortalUploadSession(Base, PortalRecord):
    __tablename__ = "portal_upload_sessions"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_portal_upload_session_storage_key"),
        Index(
            "ix_portal_upload_sessions_application_status",
            "application_id",
            "status",
        ),
        Index(
            "ix_portal_upload_sessions_tenant_creator",
            "tenant_id",
            "created_by_subject",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="SET NULL"), nullable=True
    )
    condition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("underwriting_conditions.id", ondelete="SET NULL"), nullable=True
    )
    document_type: Mapped[str] = mapped_column(String(80))
    original_file_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    created_by_subject: Mapped[str] = mapped_column(String(255), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)
