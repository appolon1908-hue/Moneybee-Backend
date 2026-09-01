from datetime import datetime
from decimal import Decimal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import AdverseActionNoticeRead, CommercialFinancingDisclosureRead


class ComplianceOverviewRead(BaseModel):
    adverse_action_notices: int
    adverse_action_notices_pending_delivery: int
    commercial_financing_disclosures: int
    commercial_financing_disclosures_unacknowledged: int
    commission_tax_records: int
    commission_tax_records_requiring_1099: int
    commission_tax_records_missing_tin: int
    generated_at: datetime


class AdverseActionNoticePage(BaseModel):
    items: list[AdverseActionNoticeRead]
    total: int
    limit: int
    offset: int
    has_more: bool


class CommercialFinancingDisclosurePage(BaseModel):
    items: list[CommercialFinancingDisclosureRead]
    total: int
    limit: int
    offset: int
    has_more: bool


class CommissionTaxRecordOperatorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recipient_type: str
    recipient_reference: str
    recipient_name: str | None
    tax_year: int
    total_amount: Decimal
    commission_count: int
    requires_1099: bool
    tin_present: bool
    filed_at: datetime | None
    filing_reference: str | None


class CommissionTaxRecordPage(BaseModel):
    items: list[CommissionTaxRecordOperatorRead]
    total: int
    limit: int
    offset: int
    has_more: bool


class CommissionTaxRecordTinInput(BaseModel):
    recipient_name: str = Field(min_length=1, max_length=255)
    tin: str = Field(min_length=9, max_length=20)


class CommissionTaxRecordFilingInput(BaseModel):
    filing_reference: str = Field(min_length=1, max_length=255)
