import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LeadCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    contact_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=40)
    source: str = Field(default="web", max_length=80)
    consent_version: str = Field(min_length=1, max_length=40)


class LeadRead(LeadCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime


class ApplicationCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    contact_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=40)
    requested_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    annual_revenue: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    consent_version: str = Field(min_length=1, max_length=40)
    consent_to_terms: Literal[True]


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_name: str
    contact_name: str
    email: EmailStr
    phone: str
    requested_amount: Decimal
    annual_revenue: Decimal | None
    consent_version: str
    status: str
    owner_subject: str
    consented_at: datetime
    created_at: datetime
    updated_at: datetime


class OfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    application_id: uuid.UUID
    lender_code: str
    product_name: str
    amount: Decimal
    term_months: int | None
    status: str


class PrincipalRead(BaseModel):
    subject: str
    roles: list[str]


class HealthRead(BaseModel):
    status: str
    database: str | None = None
    redis: str | None = None
