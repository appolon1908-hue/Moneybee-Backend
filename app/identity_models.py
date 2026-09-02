import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db_base import Base
from app.models import Record


class User(Base, Record):
    __tablename__ = "users"

    username: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_source: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ExternalIdentity(Base, Record):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(255))
    email_at_link_time: Mapped[str | None] = mapped_column(
        String(320), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Organization(Base, Record):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "organization_type IN ('BORROWER', 'LENDER', 'MONEYBEE', 'AFFILIATE')",
            name="ck_organizations_type",
        ),
    )

    name: Mapped[str] = mapped_column(String(255))
    organization_type: Mapped[str] = mapped_column(String(40), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class OrganizationMembership(Base, Record):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            "membership_type",
            name="uq_organization_membership_identity",
        ),
        CheckConstraint(
            "membership_type IN ('BORROWER', 'LENDER', 'MONEYBEE', 'AFFILIATE')",
            name="ck_organization_memberships_type",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    membership_type: Mapped[str] = mapped_column(String(40), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Role(Base, Record):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Permission(Base, Record):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)


class RolePermission(Base, Record):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "role_id", "permission_id", name="uq_role_permission_identity"
        ),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), index=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("permissions.id"), index=True
    )


class UserRoleBinding(Base, Record):
    __tablename__ = "user_role_bindings"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role_id",
            "organization_id",
            name="uq_user_role_binding_identity",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
