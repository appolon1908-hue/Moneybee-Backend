import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


TaskStatus = Literal["OPEN", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"]
TaskPriority = Literal["LOW", "NORMAL", "HIGH", "URGENT"]


class ORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PortalTaskCreate(BaseModel):
    application_id: uuid.UUID | None = None
    task_type: str = Field(default="GENERAL", min_length=2, max_length=80)
    title: str = Field(min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    priority: TaskPriority = "NORMAL"
    assigned_to_subject: str | None = Field(default=None, max_length=255)
    due_at: datetime | None = None
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


class PortalTaskUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assigned_to_subject: str | None = Field(default=None, max_length=255)
    due_at: datetime | None = None
    description: str | None = Field(default=None, max_length=10_000)


class PortalTaskRead(ORMRead):
    id: uuid.UUID
    tenant_id: uuid.UUID
    application_id: uuid.UUID | None
    task_type: str
    title: str
    description: str | None
    status: str
    priority: str
    assigned_to_subject: str | None
    created_by_subject: str
    due_at: datetime | None
    completed_at: datetime | None
    version: int
    metadata_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PortalNotificationRead(ORMRead):
    id: uuid.UUID
    tenant_id: uuid.UUID
    recipient_subject: str
    notification_type: str
    title: str
    body: str
    href: str | None
    read_at: datetime | None
    metadata_payload: dict[str, Any]
    created_at: datetime


class PortalConversationCreate(BaseModel):
    application_id: uuid.UUID | None = None
    topic: str = Field(min_length=2, max_length=240)
    participant_subjects: list[str] = Field(default_factory=list, max_length=50)
    opening_message: str | None = Field(default=None, min_length=1, max_length=20_000)
    metadata_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("participant_subjects")
    @classmethod
    def unique_participants(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        return list(dict.fromkeys(normalized))


class PortalConversationRead(ORMRead):
    id: uuid.UUID
    tenant_id: uuid.UUID
    application_id: uuid.UUID | None
    topic: str
    status: str
    created_by_subject: str
    participant_subjects: list[str]
    last_message_at: datetime
    metadata_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PortalMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


class PortalMessageRead(ORMRead):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_subject: str
    body: str
    attachments: list[dict[str, Any]]
    metadata_payload: dict[str, Any]
    created_at: datetime


class UploadSessionCreate(BaseModel):
    owner_id: uuid.UUID | None = None
    condition_id: uuid.UUID | None = None
    document_type: str = Field(min_length=2, max_length=80)
    original_file_name: str = Field(min_length=1, max_length=500)
    mime_type: str = Field(min_length=3, max_length=255)
    size_bytes: int = Field(gt=0, le=25 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


class UploadSessionComplete(BaseModel):
    provider_etag: str | None = Field(default=None, max_length=255)


class UploadSessionRead(ORMRead):
    id: uuid.UUID
    tenant_id: uuid.UUID
    application_id: uuid.UUID
    owner_id: uuid.UUID | None
    condition_id: uuid.UUID | None
    document_type: str
    original_file_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: str
    created_by_subject: str
    expires_at: datetime
    completed_at: datetime | None
    created_at: datetime


class UploadSessionIssued(BaseModel):
    session: UploadSessionRead
    upload_url: str
    upload_method: Literal["PUT"] = "PUT"
    upload_headers: dict[str, str]


class NavigationItem(BaseModel):
    key: str
    label: str
    href: str
    portal: Literal["borrower", "lender", "admin", "shared"]


class AuthContextRead(BaseModel):
    user_id: uuid.UUID
    subject: str
    active_organization_id: uuid.UUID
    organization_ids: list[uuid.UUID]
    roles: list[str]
    permissions: list[str]
    membership_types: list[str]
    borrower_id: uuid.UUID | None
    lender_id: uuid.UUID | None
    navigation: list[NavigationItem]
