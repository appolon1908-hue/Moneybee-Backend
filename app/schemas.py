import uuid
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
    requested_amount: Decimal
    monthly_revenue: Decimal
    time_in_business_months: int
    industry: str | None
    state: str | None
    status: str
    completion_percentage: int
    version: int


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
