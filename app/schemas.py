import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Attribution(BaseModel):
    landing_page: str
    original_referrer: str | None = None
    referrer: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    gclid: str | None = None
    fbclid: str | None = None
    affiliate: str | None = None


class ConsentInput(BaseModel):
    type: str
    document_version: str
    accepted: bool


class PrequalificationInput(BaseModel):
    funding_amount: Decimal = Field(ge=1000, le=10_000_000)
    currency: Literal["USD"] = "USD"
    use_of_funds: str
    time_in_business_months: int = Field(ge=0)
    monthly_revenue: Decimal = Field(ge=0)
    business_name: str = Field(min_length=2, max_length=240)
    first_name: str
    last_name: str
    email: EmailStr
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    postal_code: str
    consents: list[ConsentInput] = Field(min_length=1)
    marketing: Attribution
    anti_bot_token: str | None = None


class LeadAccepted(BaseModel):
    lead_id: uuid.UUID
    reference: str
    status: Literal["RECEIVED"] = "RECEIVED"
    next_action: dict[str, str]
    request_id: str


class ApplicationCreate(BaseModel):
    lead_id: uuid.UUID


class ApplicationUpdate(BaseModel):
    requested_amount: Decimal | None = Field(default=None, ge=1000)
    monthly_revenue: Decimal | None = Field(default=None, ge=0)
    time_in_business_months: int | None = Field(default=None, ge=0)
    industry: str | None = None
    state: str | None = Field(default=None, min_length=2, max_length=2)
    version: int


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    lead_id: uuid.UUID
    borrower_subject: str | None
    requested_amount: Decimal
    monthly_revenue: Decimal
    time_in_business_months: int
    industry: str | None
    state: str | None
    status: str
    completion_percentage: int
    version: int


class BusinessInput(BaseModel):
    legal_name: str = Field(min_length=2, max_length=240)
    dba: str | None = Field(default=None, max_length=240)
    entity_type: str | None = Field(default=None, max_length=80)
    state_formed: str | None = Field(default=None, min_length=2, max_length=2)
    industry: str | None = Field(default=None, max_length=120)
    naics: str | None = Field(default=None, max_length=12)
    website: str | None = Field(default=None, max_length=500)
    address: dict = Field(default_factory=dict)


class BusinessRead(BusinessInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    application_id: uuid.UUID


class FinancialProfileInput(BaseModel):
    annual_revenue: Decimal | None = Field(default=None, ge=0)
    monthly_revenue: Decimal | None = Field(default=None, ge=0)
    monthly_expenses: Decimal | None = Field(default=None, ge=0)
    existing_debt: Decimal | None = Field(default=None, ge=0)
    existing_positions: int = Field(default=0, ge=0)


class FinancialProfileRead(FinancialProfileInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    application_id: uuid.UUID


class OwnerInput(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    ownership_percent: Decimal = Field(gt=0, le=100)
    title: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    address: dict = Field(default_factory=dict)


class OwnerRead(OwnerInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    application_id: uuid.UUID


class ProgramInput(BaseModel):
    lender_id: uuid.UUID
    name: str
    product_type: str
    min_amount: Decimal
    max_amount: Decimal
    minimum_monthly_revenue: Decimal
    minimum_time_in_business_months: int
    states: list[str] = Field(default_factory=list)
    excluded_industries: list[str] = Field(default_factory=list)


class ProgramRead(ProgramInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    active: bool
    version: int


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    lender_id: uuid.UUID
    program_id: uuid.UUID
    eligible: bool
    score: int
    reasons: list[str]
    program_version: int


class OfferInput(BaseModel):
    application_id: uuid.UUID
    lender_id: uuid.UUID
    program_id: uuid.UUID | None = None
    product_type: str
    amount: Decimal = Field(gt=0)
    term_months: int = Field(gt=0)
    payment_frequency: str
    payment_amount: Decimal = Field(gt=0)
    apr: Decimal | None = None
    factor_rate: Decimal | None = None
    origination_fee: Decimal = 0
    total_repayment: Decimal | None = None


class OfferRead(OfferInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    version: int


class CreditAuthorizationInput(BaseModel):
    authorization_version: str = Field(min_length=1, max_length=50)
    document_hash: str = Field(min_length=32, max_length=128)
    accepted: Literal[True]


class CreditAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    application_id: uuid.UUID
    authorization_version: str
    document_hash: str
    accepted_by: str
    accepted_at: datetime


class ComplaintInput(BaseModel):
    category: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=10, max_length=10_000)
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"


class ComplaintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    application_id: uuid.UUID | None
    created_by: str
    category: str
    description: str
    priority: str
    status: str
    resolution: str | None
    created_at: datetime


class ConditionInput(BaseModel):
    description: str = Field(min_length=3, max_length=5_000)


class ConditionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    submission_id: uuid.UUID
    application_id: uuid.UUID
    description: str
    status: str
    created_at: datetime


class LenderSubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    application_id: uuid.UUID
    lender_id: uuid.UUID
    program_id: uuid.UUID
    program_version: int
    external_submission_id: str | None
    status: str
    submitted_at: datetime | None
    created_at: datetime


class FundingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    application_id: uuid.UUID
    offer_id: uuid.UUID
    status: str
    approved_amount: Decimal | None
    funded_amount: Decimal | None
    provider_reference: str | None
    funding_confirmed_at: datetime | None
    created_at: datetime


class CommissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    funding_id: uuid.UUID
    expected_amount: Decimal
    received_amount: Decimal
    status: str
    created_at: datetime


class RenewalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    original_funding_id: uuid.UUID
    application_id: uuid.UUID
    eligible_from: datetime
    eligibility_status: str
    estimated_amount: Decimal | None
    status: str
    created_at: datetime


class AffiliateInput(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    tracking_code: str = Field(min_length=3, max_length=100)
    active: bool = True


class AffiliateRead(AffiliateInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime


class NotificationPreferenceInput(BaseModel):
    email_enabled: bool = True
    sms_enabled: bool = False
    in_app_enabled: bool = True


class NotificationPreferenceRead(NotificationPreferenceInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    subject: str
    created_at: datetime
    updated_at: datetime
