import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    APPLICATION_STARTED = "APPLICATION_STARTED"
    MATCHING = "MATCHING"
    OFFERED = "OFFERED"
    FUNDED = "FUNDED"
    DUPLICATE = "DUPLICATE"
    FRAUD_REVIEW = "FRAUD_REVIEW"
    LOST = "LOST"


class ApplicationStatus(str, enum.Enum):
    APPLICATION_STARTED = "APPLICATION_STARTED"
    APPLICATION_IN_PROGRESS = "APPLICATION_IN_PROGRESS"
    READY_FOR_MATCHING = "READY_FOR_MATCHING"
    MATCHED = "MATCHED"
    OFFERS_AVAILABLE = "OFFERS_AVAILABLE"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    FUNDED = "FUNDED"
    WITHDRAWN = "WITHDRAWN"
    FRAUD_REVIEW = "FRAUD_REVIEW"


class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    DELIVERED = "DELIVERED"
    RETRY = "RETRY"
    DEAD = "DEAD"


class ProviderStatus(str, enum.Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONFIGURED = "CONFIGURED"
    VERIFYING = "VERIFYING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class Record:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Lead(Base, Record):
    __tablename__ = "leads"

    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(320), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    business_name: Mapped[str] = mapped_column(String(240), index=True)
    funding_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    monthly_revenue: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    use_of_funds: Mapped[str] = mapped_column(String(80))
    time_in_business_months: Mapped[int] = mapped_column(Integer)
    postal_code: Mapped[str] = mapped_column(String(20))
    status: Mapped[LeadStatus] = mapped_column(Enum(LeadStatus), default=LeadStatus.NEW)
    attribution: Mapped[dict] = mapped_column(JSON, default=dict)


class Consent(Base, Record):
    __tablename__ = "consents"

    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id"), nullable=True
    )
    consent_type: Mapped[str] = mapped_column(String(100))
    document_version: Mapped[str] = mapped_column(String(80))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class Application(Base, Record):
    __tablename__ = "applications"

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id"), unique=True)
    borrower_subject: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    monthly_revenue: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    time_in_business_months: Mapped[int] = mapped_column(Integer)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus), default=ApplicationStatus.APPLICATION_STARTED
    )
    completion_percentage: Mapped[int] = mapped_column(Integer, default=20)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ApplicationStatusHistory(Base, Record):
    __tablename__ = "application_status_history"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    to_status: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(200))


class Business(Base, Record):
    __tablename__ = "businesses"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), unique=True, index=True
    )
    legal_name: Mapped[str] = mapped_column(String(240))
    dba: Mapped[str | None] = mapped_column(String(240), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state_formed: Mapped[str | None] = mapped_column(String(2), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    naics: Mapped[str | None] = mapped_column(String(12), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address: Mapped[dict] = mapped_column(JSON, default=dict)


class Owner(Base, Record):
    __tablename__ = "owners"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    ownership_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[dict] = mapped_column(JSON, default=dict)


class FinancialProfile(Base, Record):
    __tablename__ = "financial_profiles"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), unique=True, index=True
    )
    annual_revenue: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    monthly_revenue: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    monthly_expenses: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    existing_debt: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    existing_positions: Mapped[int] = mapped_column(Integer, default=0)


class LenderProgram(Base, Record):
    __tablename__ = "lender_programs"

    lender_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(200))
    product_type: Mapped[str] = mapped_column(String(80))
    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    minimum_monthly_revenue: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    minimum_time_in_business_months: Mapped[int] = mapped_column(Integer)
    states: Mapped[list] = mapped_column(JSON, default=list)
    excluded_industries: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ApplicationMatch(Base, Record):
    __tablename__ = "application_matches"

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    lender_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    program_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lender_programs.id"))
    eligible: Mapped[bool]
    score: Mapped[int]
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    program_version: Mapped[int]


class Offer(Base, Record):
    __tablename__ = "offers"

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    lender_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    program_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lender_programs.id"), nullable=True
    )
    product_type: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    term_months: Mapped[int]
    payment_frequency: Mapped[str] = mapped_column(String(40))
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    apr: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    factor_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    origination_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_repayment: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="AVAILABLE")
    version: Mapped[int] = mapped_column(Integer, default=1)


class OutboxEvent(Base, Record):
    __tablename__ = "outbox_events"

    event_type: Mapped[str] = mapped_column(String(120), index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payload: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[OutboxStatus] = mapped_column(Enum(OutboxStatus), default=OutboxStatus.PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base, Record):
    __tablename__ = "audit_events"

    actor_id: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(120))
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class CapabilityFlag(Base, Record):
    __tablename__ = "capability_flags"

    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(40), index=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled_by: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ProviderConnection(Base, Record):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint(
            "provider_type",
            "provider_name",
            "environment",
            name="uq_provider_connection_identity",
        ),
    )

    provider_type: Mapped[str] = mapped_column(String(80), index=True)
    provider_name: Mapped[str] = mapped_column(String(120), index=True)
    environment: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[ProviderStatus] = mapped_column(
        Enum(ProviderStatus), default=ProviderStatus.NOT_CONFIGURED
    )
    external_account_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    configuration_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
