from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PortalOrganization(BaseModel):
    id: uuid.UUID
    name: str
    organization_type: str


class PortalContext(BaseModel):
    user_id: uuid.UUID
    subject: str
    active_organization_id: uuid.UUID | None
    organizations: list[PortalOrganization]
    roles: list[str]
    permissions: list[str]
    membership_types: list[str]
    portal: Literal["BORROWER", "LENDER", "ADMIN", "AFFILIATE", "UNKNOWN"]
    capabilities: dict[str, bool]


class NavigationItem(BaseModel):
    key: str
    label: str
    path: str
    group: str
    required_permission: str | None = None


class PortalTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    assignee_subject: str | None
    task_type: str
    title: str
    description: str | None
    status: str
    priority: str
    due_at: datetime | None
    completed_at: datetime | None
    source_type: str | None
    source_reference: str | None
    metadata_payload: dict
    created_at: datetime
    updated_at: datetime


class PortalTaskUpdate(BaseModel):
    status: Literal["OPEN", "IN_PROGRESS", "COMPLETED", "DISMISSED"]


class PortalTaskCreate(BaseModel):
    application_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    assignee_user_id: uuid.UUID | None = None
    assignee_subject: str | None = Field(default=None, max_length=255)
    task_type: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"
    due_at: datetime | None = None
    source_type: str | None = Field(default=None, max_length=100)
    source_reference: str | None = Field(default=None, max_length=255)
    metadata_payload: dict = Field(default_factory=dict)


class PortalNotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    subject: str
    category: str
    title: str
    body: str
    action_path: str | None
    read_at: datetime | None
    metadata_payload: dict
    created_at: datetime


class PortalNotificationCreate(BaseModel):
    application_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    subject: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=255)
    body: str = Field(min_length=2, max_length=10_000)
    action_path: str | None = Field(default=None, max_length=500)
    metadata_payload: dict = Field(default_factory=dict)


class ConversationCreate(BaseModel):
    application_id: uuid.UUID | None = None
    topic: str = Field(min_length=2, max_length=255)
    body: str = Field(min_length=1, max_length=20_000)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    topic: str
    status: str
    created_by_subject: str
    last_message_at: datetime | None
    created_at: datetime


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    attachment_document_id: uuid.UUID | None = None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_subject: str
    sender_type: str
    body: str
    message_type: str
    attachment_document_id: uuid.UUID | None
    metadata_payload: dict
    created_at: datetime


class UploadSessionCreate(BaseModel):
    document_type: str = Field(min_length=2, max_length=100)
    original_file_name: str = Field(min_length=1, max_length=500)
    mime_type: str = Field(min_length=3, max_length=255)
    size_bytes: int = Field(gt=0, le=25 * 1024 * 1024)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class UploadSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    document_type: str
    original_file_name: str
    mime_type: str
    size_bytes: int
    expected_sha256: str | None
    status: str
    expires_at: datetime
    upload_url: str | None = None
    upload_headers: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


class UploadSessionComplete(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    size_bytes: int = Field(gt=0, le=25 * 1024 * 1024)


class PageMeta(BaseModel):
    limit: int
    offset: int
    total: int


class BorrowerOverview(BaseModel):
    active_application: dict | None
    applications: list[dict]
    requirements: dict | None
    open_tasks: int
    unread_notifications: int
    open_conditions: int
    available_offers: int
    recent_activity: list[dict]


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    owner_id: uuid.UUID | None
    condition_id: uuid.UUID | None
    document_type: str
    original_file_name: str
    mime_type: str | None
    size_bytes: int
    sha256: str
    status: str
    uploaded_by: str
    created_at: datetime
    updated_at: datetime


class DocumentDownload(BaseModel):
    download_url: str
    expires_seconds: int
