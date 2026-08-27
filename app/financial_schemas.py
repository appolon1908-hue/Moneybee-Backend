import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _currency(value: str) -> str:
    value = value.strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError("currency must be a three-letter ISO code")
    return value


class LedgerAccountCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    account_type: str
    currency: str = "USD"

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"}:
            raise ValueError("unsupported account type")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return _currency(value)


class LedgerAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    code: str
    name: str
    account_type: str
    currency: str
    active: bool
    system_managed: bool


class AccountingPeriodCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=80)
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def valid_range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AccountingPeriodRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    starts_at: datetime
    ends_at: datetime
    status: str
    closed_at: datetime | None
    closed_by: str | None


class PostingInput(BaseModel):
    account_id: uuid.UUID
    side: str
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    application_id: uuid.UUID | None = None
    funding_id: uuid.UUID | None = None
    commission_id: uuid.UUID | None = None
    bank_transaction_id: uuid.UUID | None = None
    memo: str | None = Field(default=None, max_length=500)
    metadata_payload: dict = Field(default_factory=dict)

    @field_validator("side")
    @classmethod
    def validate_side(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in {"DEBIT", "CREDIT"}:
            raise ValueError("side must be DEBIT or CREDIT")
        return value


class JournalEntryCreate(BaseModel):
    organization_id: uuid.UUID | None = None
    # Transitional body field for older clients. The Idempotency-Key header is canonical.
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)
    source_type: str = Field(min_length=1, max_length=80)
    source_id: str | None = Field(default=None, max_length=255)
    description: str = Field(min_length=1, max_length=2000)
    currency: str = "USD"
    effective_at: datetime
    metadata_payload: dict = Field(default_factory=dict)
    postings: list[PostingInput] = Field(min_length=2)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return _currency(value)

    @field_validator("source_type")
    @classmethod
    def normalize_source_type(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def balanced(self):
        debits = sum((item.amount for item in self.postings if item.side == "DEBIT"), Decimal("0"))
        credits = sum((item.amount for item in self.postings if item.side == "CREDIT"), Decimal("0"))
        if debits != credits:
            raise ValueError("journal entry must balance: total debits must equal total credits")
        return self


class PostingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    journal_entry_id: uuid.UUID
    account_id: uuid.UUID
    side: str
    amount: Decimal
    currency: str
    application_id: uuid.UUID | None
    funding_id: uuid.UUID | None
    commission_id: uuid.UUID | None
    bank_transaction_id: uuid.UUID | None
    memo: str | None


class JournalEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    period_id: uuid.UUID | None
    entry_number: str
    idempotency_key: str
    source_type: str
    source_id: str | None
    description: str
    currency: str
    effective_at: datetime
    status: str
    posted_at: datetime
    posted_by: str
    reversal_of_id: uuid.UUID | None


class TrialBalanceLine(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    account_type: str
    debit_total: Decimal
    credit_total: Decimal
    balance: Decimal


class TrialBalanceRead(BaseModel):
    organization_id: uuid.UUID
    currency: str
    as_of: datetime
    debit_total: Decimal
    credit_total: Decimal
    balanced: bool
    accounts: list[TrialBalanceLine]
