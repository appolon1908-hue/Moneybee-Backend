from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class MarketingAttribution(BaseModel):
    landing_page: str = Field(min_length=1, max_length=160)
    original_referrer: str | None = Field(default=None, max_length=1000)
    referrer: str | None = Field(default=None, max_length=1000)
    utm_source: str | None = Field(default=None, max_length=200)
    utm_medium: str | None = Field(default=None, max_length=200)
    utm_campaign: str | None = Field(default=None, max_length=200)
    utm_content: str | None = Field(default=None, max_length=300)
    utm_term: str | None = Field(default=None, max_length=300)
    gclid: str | None = Field(default=None, max_length=300)
    fbclid: str | None = Field(default=None, max_length=300)
    affiliate: str | None = Field(default=None, max_length=200)


class PublicConsentInput(BaseModel):
    type: str = Field(min_length=2, max_length=100)
    document_version: str = Field(min_length=1, max_length=80)
    document_hash: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    accepted: bool


class PublicIntakeCommon(BaseModel):
    marketing: MarketingAttribution
    consents: list[PublicConsentInput] = Field(min_length=1, max_length=20)
    anti_bot_token: str | None = Field(default=None, max_length=4000)


class ContactRequestInput(PublicIntakeCommon):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    business_name: str | None = Field(default=None, max_length=240)
    topic: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=10, max_length=5000)
    preferred_channel: Literal["EMAIL", "PHONE", "EITHER"] = "EITHER"


class CallbackRequestInput(PublicIntakeCommon):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=40)
    business_name: str | None = Field(default=None, max_length=240)
    preferred_time: str = Field(min_length=2, max_length=120)
    timezone: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=2, max_length=240)
    message: str | None = Field(default=None, max_length=3000)


class LenderPartnerInquiryInput(PublicIntakeCommon):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    institution_name: str = Field(min_length=2, max_length=240)
    role: str = Field(min_length=2, max_length=120)
    website: str | None = Field(default=None, max_length=500)
    product_types: list[str] = Field(default_factory=list, max_length=30)
    states: list[str] = Field(default_factory=list, max_length=60)
    annual_originations: Decimal | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=5000)


class ReferralPartnerInquiryInput(PublicIntakeCommon):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    company_name: str = Field(min_length=2, max_length=240)
    partner_type: Literal["BROKER", "REFERRAL_PARTNER", "ISO", "CPA", "CONSULTANT", "OTHER"]
    website: str | None = Field(default=None, max_length=500)
    states: list[str] = Field(default_factory=list, max_length=60)
    estimated_monthly_leads: int | None = Field(default=None, ge=0, le=100_000)
    message: str | None = Field(default=None, max_length=5000)


class DealSubmissionInquiryInput(PublicIntakeCommon):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=40)
    business_name: str = Field(min_length=2, max_length=240)
    requested_amount: Decimal = Field(ge=1000, le=10_000_000)
    monthly_revenue: Decimal = Field(ge=0)
    time_in_business_months: int = Field(ge=0)
    industry: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=2)
    use_of_funds: str = Field(min_length=2, max_length=120)
    message: str | None = Field(default=None, max_length=5000)


class PublicIntakeAccepted(BaseModel):
    intake_id: uuid.UUID
    reference: str
    intake_type: str
    status: Literal["RECEIVED"] = "RECEIVED"
    request_id: str


class DeliveryRequeue(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)
