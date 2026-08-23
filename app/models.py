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


class BankConnection(Base, Record):
    __tablename__ = "bank_connections"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(100))
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")


class BankAnalysis(Base, Record):
    __tablename__ = "bank_analyses"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    analysis_version: Mapped[int] = mapped_column(Integer, default=1)
    average_monthly_deposits: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    average_daily_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    negative_balance_days_90d: Mapped[int] = mapped_column(Integer, default=0)
    nsf_count_90d: Mapped[int] = mapped_column(Integer, default=0)
    deposit_count_90d: Mapped[int] = mapped_column(Integer, default=0)
    largest_deposit_90d: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    existing_payment_obligations: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    revenue_trend: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cash_flow_trend: Mapped[str | None] = mapped_column(String(40), nullable=True)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)


class Verification(Base, Record):
    __tablename__ = "verifications"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id"), nullable=True
    )
    verification_type: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(100))
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    normalized_result: Mapped[dict] = mapped_column(JSON, default=dict)


class CreditAuthorization(Base, Record):
    __tablename__ = "credit_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "authorization_version",
            name="uq_credit_authorization_version",
        ),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    authorization_version: Mapped[str] = mapped_column(String(50))
    document_hash: Mapped[str] = mapped_column(String(128))
    accepted_by: Mapped[str] = mapped_column(String(200))
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class CreditResult(Base, Record):
    __tablename__ = "credit_results"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(100))
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_result: Mapped[dict] = mapped_column(JSON, default=dict)


class FraudAssessment(Base, Record):
    __tablename__ = "fraud_assessments"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    policy_version: Mapped[int] = mapped_column(Integer, default=1)
    score: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(40))
    flags: Mapped[list] = mapped_column(JSON, default=list)


class LenderSubmission(Base, Record):
    __tablename__ = "lender_submissions"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "program_id",
            "program_version",
            name="uq_submission_application_program_version",
        ),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    lender_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lender_programs.id")
    )
    program_version: Mapped[int] = mapped_column(Integer)
    external_submission_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    status: Mapped[str] = mapped_column(String(60), default="QUEUED")
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UnderwritingCondition(Base, Record):
    __tablename__ = "underwriting_conditions"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lender_submissions.id"), index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(60), default="BORROWER_ACTION_REQUIRED"
    )


class Document(Base, Record):
    __tablename__ = "documents"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id"), nullable=True
    )
    condition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("underwriting_conditions.id"), nullable=True
    )
    document_type: Mapped[str] = mapped_column(String(80))
    original_file_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="QUARANTINED")
    uploaded_by: Mapped[str] = mapped_column(String(200))


class Contract(Base, Record):
    __tablename__ = "contracts"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id"))
    template_version: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_envelope_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    document_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(60), default="DRAFT")
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Funding(Base, Record):
    __tablename__ = "fundings"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), unique=True, index=True
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offers.id"), unique=True
    )
    status: Mapped[str] = mapped_column(
        String(60), default="CONDITIONS_PENDING"
    )
    approved_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    funded_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    provider_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    funds_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    funding_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Commission(Base, Record):
    __tablename__ = "commissions"

    funding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fundings.id"), unique=True, index=True
    )
    expected_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    received_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0
    )
    status: Mapped[str] = mapped_column(String(40), default="EXPECTED")


class RenewalOpportunity(Base, Record):
    __tablename__ = "renewal_opportunities"

    original_funding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fundings.id"), unique=True, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    eligible_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    eligibility_status: Mapped[str] = mapped_column(
        String(40), default="PENDING"
    )
    estimated_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    status: Mapped[str] = mapped_column(String(40), default="PENDING")


class Complaint(Base, Record):
    __tablename__ = "complaints"

    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(30), default="NORMAL")
    status: Mapped[str] = mapped_column(String(40), default="OPEN")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)


class Affiliate(Base, Record):
    __tablename__ = "affiliates"

    name: Mapped[str] = mapped_column(String(255))
    tracking_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    active: Mapped[bool] = mapped_column(default=True)


class Communication(Base, Record):
    __tablename__ = "communications"

    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id"), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(String(30))
    recipient_reference: Mapped[str] = mapped_column(String(320))
    template_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="QUEUED")
    provider_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class IntegrationEvent(Base, Record):
    __tablename__ = "integration_events"

    provider: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(120))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[dict] = mapped_column(JSON, default=dict)


class IdempotencyRecord(Base, Record):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "route",
            "key",
            name="uq_idempotency_actor_route_key",
        ),
    )

    key: Mapped[str] = mapped_column(String(160), index=True)
    actor_id: Mapped[str] = mapped_column(String(200))
    route: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(128))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSON)
