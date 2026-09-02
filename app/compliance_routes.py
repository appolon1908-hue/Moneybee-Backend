import hashlib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import compliance_models, models, services
from app.auth import Principal, current_principal, require_permission
from app.compliance_schemas import (
    AdverseActionNoticePage,
    CommissionTaxRecordFilingInput,
    CommissionTaxRecordOperatorRead,
    CommissionTaxRecordPage,
    CommissionTaxRecordTinInput,
    CommercialFinancingDisclosurePage,
    ComplianceOverviewRead,
)
from app.compliance_service import generate_commission_tax_records, update_recipient_tin
from app.db import get_db
from app.schemas import CommercialFinancingDisclosureRead


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=160),
]
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0, le=100_000)]


def _problem(code: str, message: str, status_code: int = 409) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _request_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _tax_record_read(
    record: compliance_models.CommissionTaxRecord,
) -> CommissionTaxRecordOperatorRead:
    return CommissionTaxRecordOperatorRead(
        id=record.id,
        recipient_type=record.recipient_type,
        recipient_reference=record.recipient_reference,
        recipient_name=record.recipient_name,
        tax_year=record.tax_year,
        total_amount=record.total_amount,
        commission_count=record.commission_count,
        requires_1099=record.requires_1099,
        tin_present=record.tin_ciphertext is not None,
        filed_at=record.filed_at,
        filing_reference=record.filing_reference,
    )


async def _disclosure_for_offer(
    db: AsyncSession,
    offer_id: uuid.UUID,
    *,
    lock: bool = False,
) -> compliance_models.CommercialFinancingDisclosure:
    statement = select(compliance_models.CommercialFinancingDisclosure).where(
        compliance_models.CommercialFinancingDisclosure.offer_id == offer_id
    )
    if lock:
        statement = statement.with_for_update()
    disclosure = await db.scalar(statement)
    if disclosure is None:
        raise HTTPException(status_code=404, detail="Disclosure not found")
    return disclosure


async def _acknowledge_disclosure(
    *,
    db: AsyncSession,
    disclosure: compliance_models.CommercialFinancingDisclosure,
    user: Principal,
    idempotency_key: str,
    route: str,
) -> CommercialFinancingDisclosureRead | dict:
    request_hash = _request_hash(
        {
            "offer_id": str(disclosure.offer_id),
            "application_id": str(disclosure.application_id),
        }
    )
    existing = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == user.subject,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            _problem(
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key was already used for a different disclosure.",
            )
        return existing.response_body

    if disclosure.acknowledged_at is None:
        disclosure.acknowledged_at = models.utcnow()
        disclosure.acknowledged_by = user.subject
        db.add(
            models.AuditEvent(
                actor_id=user.subject,
                action="COMMERCIAL_FINANCING_DISCLOSURE_ACKNOWLEDGED",
                resource_type="commercial_financing_disclosure",
                resource_id=str(disclosure.id),
                details={
                    "offer_id": str(disclosure.offer_id),
                    "application_id": str(disclosure.application_id),
                },
            )
        )

    response = CommercialFinancingDisclosureRead.model_validate(disclosure)
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body=response.model_dump(mode="json"),
        )
    )
    await db.commit()
    # Not db.refresh(disclosure) + re-validate: SQLite drops tzinfo on a
    # DateTime round-trip, so re-reading acknowledged_at here would
    # serialize it differently (no "Z") than the idempotency snapshot
    # above already captured from the same in-memory value - the one
    # thing that must stay byte-identical on replay.
    return response


@router.get(
    "/admin/compliance/overview",
    response_model=ComplianceOverviewRead,
    tags=["admin", "compliance"],
    operation_id="admin_compliance_overview",
)
async def compliance_overview(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.read"))],
):
    adverse_total = int(
        await db.scalar(
            select(func.count()).select_from(compliance_models.AdverseActionNotice)
        )
        or 0
    )
    adverse_pending = int(
        await db.scalar(
            select(func.count())
            .select_from(compliance_models.AdverseActionNotice)
            .where(compliance_models.AdverseActionNotice.delivered_at.is_(None))
        )
        or 0
    )
    disclosures_total = int(
        await db.scalar(
            select(func.count()).select_from(
                compliance_models.CommercialFinancingDisclosure
            )
        )
        or 0
    )
    disclosures_unacknowledged = int(
        await db.scalar(
            select(func.count())
            .select_from(compliance_models.CommercialFinancingDisclosure)
            .where(
                compliance_models.CommercialFinancingDisclosure.acknowledged_at.is_(
                    None
                )
            )
        )
        or 0
    )
    tax_total = int(
        await db.scalar(
            select(func.count()).select_from(compliance_models.CommissionTaxRecord)
        )
        or 0
    )
    tax_requiring_1099 = int(
        await db.scalar(
            select(func.count())
            .select_from(compliance_models.CommissionTaxRecord)
            .where(compliance_models.CommissionTaxRecord.requires_1099.is_(True))
        )
        or 0
    )
    tax_missing_tin = int(
        await db.scalar(
            select(func.count())
            .select_from(compliance_models.CommissionTaxRecord)
            .where(
                compliance_models.CommissionTaxRecord.requires_1099.is_(True),
                compliance_models.CommissionTaxRecord.tin_ciphertext.is_(None),
            )
        )
        or 0
    )
    return ComplianceOverviewRead(
        adverse_action_notices=adverse_total,
        adverse_action_notices_pending_delivery=adverse_pending,
        commercial_financing_disclosures=disclosures_total,
        commercial_financing_disclosures_unacknowledged=disclosures_unacknowledged,
        commission_tax_records=tax_total,
        commission_tax_records_requiring_1099=tax_requiring_1099,
        commission_tax_records_missing_tin=tax_missing_tin,
        generated_at=models.utcnow(),
    )


@router.get(
    "/admin/compliance/adverse-action-notices",
    response_model=AdverseActionNoticePage,
    tags=["admin", "compliance"],
    operation_id="admin_list_adverse_action_notices",
)
async def list_all_adverse_action_notices(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.read"))],
    application_id: uuid.UUID | None = None,
    notice_status: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
):
    filters = []
    if application_id is not None:
        filters.append(
            compliance_models.AdverseActionNotice.application_id == application_id
        )
    if notice_status is not None:
        filters.append(compliance_models.AdverseActionNotice.status == notice_status)
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(compliance_models.AdverseActionNotice)
            .where(*filters)
        )
        or 0
    )
    items = list(
        (
            await db.scalars(
                select(compliance_models.AdverseActionNotice)
                .where(*filters)
                .order_by(compliance_models.AdverseActionNotice.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return AdverseActionNoticePage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )


@router.get(
    "/admin/compliance/commercial-financing-disclosures",
    response_model=CommercialFinancingDisclosurePage,
    tags=["admin", "compliance"],
    operation_id="admin_list_commercial_financing_disclosures",
)
async def list_all_commercial_financing_disclosures(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.read"))],
    application_id: uuid.UUID | None = None,
    acknowledged: bool | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
):
    filters = []
    if application_id is not None:
        filters.append(
            compliance_models.CommercialFinancingDisclosure.application_id
            == application_id
        )
    if acknowledged is True:
        filters.append(
            compliance_models.CommercialFinancingDisclosure.acknowledged_at.is_not(
                None
            )
        )
    elif acknowledged is False:
        filters.append(
            compliance_models.CommercialFinancingDisclosure.acknowledged_at.is_(None)
        )
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(compliance_models.CommercialFinancingDisclosure)
            .where(*filters)
        )
        or 0
    )
    items = list(
        (
            await db.scalars(
                select(compliance_models.CommercialFinancingDisclosure)
                .where(*filters)
                .order_by(
                    compliance_models.CommercialFinancingDisclosure.created_at.desc()
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return CommercialFinancingDisclosurePage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )


@router.get(
    "/admin/compliance/commission-tax-records",
    response_model=CommissionTaxRecordPage,
    tags=["admin", "compliance"],
    operation_id="admin_list_commission_tax_records",
)
async def list_all_commission_tax_records(
    db: Db,
    user: Annotated[
        Principal,
        Depends(require_permission("commission.receipt.record")),
    ],
    tax_year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    requires_1099: bool | None = None,
    tin_present: bool | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
):
    filters = []
    if tax_year is not None:
        filters.append(compliance_models.CommissionTaxRecord.tax_year == tax_year)
    if requires_1099 is not None:
        filters.append(
            compliance_models.CommissionTaxRecord.requires_1099.is_(requires_1099)
        )
    if tin_present is True:
        filters.append(
            compliance_models.CommissionTaxRecord.tin_ciphertext.is_not(None)
        )
    elif tin_present is False:
        filters.append(compliance_models.CommissionTaxRecord.tin_ciphertext.is_(None))
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(compliance_models.CommissionTaxRecord)
            .where(*filters)
        )
        or 0
    )
    records = list(
        (
            await db.scalars(
                select(compliance_models.CommissionTaxRecord)
                .where(*filters)
                .order_by(
                    compliance_models.CommissionTaxRecord.tax_year.desc(),
                    compliance_models.CommissionTaxRecord.total_amount.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    items = [_tax_record_read(record) for record in records]
    return CommissionTaxRecordPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )


@router.post(
    "/admin/compliance/commission-tax-records/generate",
    response_model=list[CommissionTaxRecordOperatorRead],
    tags=["admin", "compliance"],
    operation_id="admin_generate_commission_tax_records",
)
async def generate_tax_records(
    tax_year: Annotated[int, Query(ge=2000, le=2100)],
    db: Db,
    user: Annotated[
        Principal,
        Depends(require_permission("commission.receipt.record")),
    ],
    idempotency_key: IdempotencyKey,
):
    route = "/admin/compliance/commission-tax-records/generate"
    request_hash = _request_hash({"tax_year": tax_year})
    existing = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == user.subject,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            _problem(
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key was already used for a different tax year.",
            )
        return existing.response_body

    try:
        records = await generate_commission_tax_records(db, tax_year)
    except ValueError as exc:
        _problem("FILED_TAX_RECORD_IMMUTABLE", str(exc), status_code=409)
    existing = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == user.subject,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            _problem(
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key was already used for a different tax year.",
            )
        return existing.response_body
    response = [_tax_record_read(record) for record in records]
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="COMMISSION_TAX_RECORDS_GENERATED",
            resource_type="commission_tax_year",
            resource_id=str(tax_year),
            details={"record_count": len(response)},
        )
    )
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body=[item.model_dump(mode="json") for item in response],
        )
    )
    await db.commit()
    return response


@router.patch(
    "/admin/compliance/commission-tax-records/{record_id}/tin",
    response_model=CommissionTaxRecordOperatorRead,
    tags=["admin", "compliance"],
    operation_id="admin_set_commission_tax_record_tin",
)
async def set_tax_record_tin(
    record_id: uuid.UUID,
    payload: CommissionTaxRecordTinInput,
    db: Db,
    user: Annotated[
        Principal,
        Depends(require_permission("commission.receipt.record")),
    ],
):
    record = await db.scalar(
        select(compliance_models.CommissionTaxRecord)
        .where(compliance_models.CommissionTaxRecord.id == record_id)
        .with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Commission tax record not found")
    await update_recipient_tin(
        db,
        record,
        recipient_name=payload.recipient_name,
        tin=payload.tin,
    )
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="COMMISSION_TAX_RECORD_TIN_UPDATED",
            resource_type="commission_tax_record",
            resource_id=str(record.id),
            details={
                "recipient_reference": record.recipient_reference,
                "tin_present": True,
            },
        )
    )
    await db.commit()
    # Not db.refresh(record): nothing server-generated changed, and SQLite
    # drops tzinfo on a DateTime round-trip, so re-reading filed_at (if
    # already set from an earlier filing) would serialize it without "Z" -
    # an inconsistent representation of the same field across endpoints.
    return _tax_record_read(record)


@router.patch(
    "/admin/compliance/commission-tax-records/{record_id}/filing",
    response_model=CommissionTaxRecordOperatorRead,
    tags=["admin", "compliance"],
    operation_id="admin_record_commission_tax_filing",
)
async def record_tax_filing(
    record_id: uuid.UUID,
    payload: CommissionTaxRecordFilingInput,
    db: Db,
    user: Annotated[
        Principal,
        Depends(require_permission("commission.receipt.record")),
    ],
    idempotency_key: IdempotencyKey,
):
    route = f"/admin/compliance/commission-tax-records/{record_id}/filing"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    existing = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == user.subject,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            _problem(
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key was already used with different filing evidence.",
            )
        return existing.response_body

    record = await db.scalar(
        select(compliance_models.CommissionTaxRecord)
        .where(compliance_models.CommissionTaxRecord.id == record_id)
        .with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Commission tax record not found")
    # The row lock serializes concurrent calls. Re-read the idempotency
    # identity after acquiring it because another transaction may have
    # committed the same key while this request was waiting.
    existing = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == user.subject,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            _problem(
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key was already used with different filing evidence.",
            )
        return existing.response_body
    if (
        record.filed_at is not None
        and record.filing_reference != payload.filing_reference
    ):
        _problem(
            "FILING_ALREADY_RECORDED",
            "This tax record already has different filing evidence.",
        )
    if record.filed_at is None:
        record.filed_at = models.utcnow()
        record.filing_reference = payload.filing_reference
        db.add(
            models.AuditEvent(
                actor_id=user.subject,
                action="COMMISSION_TAX_RECORD_FILED",
                resource_type="commission_tax_record",
                resource_id=str(record.id),
                details={"filing_reference": payload.filing_reference},
            )
        )
    response = _tax_record_read(record)
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body=response.model_dump(mode="json"),
        )
    )
    await db.commit()
    # Not db.refresh(record) + re-read: SQLite drops tzinfo on a DateTime
    # round-trip, so re-reading filed_at here would serialize it
    # differently (no "Z") than the idempotency snapshot above already
    # captured from the same in-memory value - the one thing that must
    # stay byte-identical on replay.
    return response


@router.get(
    "/borrower/offers/{offer_id}/commercial-financing-disclosure",
    response_model=CommercialFinancingDisclosureRead,
    tags=["borrower", "compliance"],
    operation_id="borrower_get_commercial_financing_disclosure",
)
async def borrower_get_disclosure(
    offer_id: uuid.UUID,
    db: Db,
    user: User,
):
    disclosure = await _disclosure_for_offer(db, offer_id)
    await services.get_authorized_application(
        db,
        disclosure.application_id,
        user,
        write=False,
    )
    return disclosure


@router.post(
    "/borrower/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
    response_model=CommercialFinancingDisclosureRead,
    tags=["borrower", "compliance"],
    operation_id="borrower_acknowledge_commercial_financing_disclosure",
)
async def borrower_acknowledge_disclosure(
    offer_id: uuid.UUID,
    db: Db,
    user: User,
    idempotency_key: IdempotencyKey,
):
    disclosure = await _disclosure_for_offer(db, offer_id, lock=True)
    await services.get_authorized_application(
        db,
        disclosure.application_id,
        user,
        write=True,
    )
    return await _acknowledge_disclosure(
        db=db,
        disclosure=disclosure,
        user=user,
        idempotency_key=idempotency_key,
        route=f"/borrower/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
    )


@router.post(
    "/admin/compliance/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
    response_model=CommercialFinancingDisclosureRead,
    tags=["admin", "compliance"],
    operation_id="admin_acknowledge_commercial_financing_disclosure",
)
async def admin_acknowledge_disclosure(
    offer_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.edit"))],
    idempotency_key: IdempotencyKey,
):
    disclosure = await _disclosure_for_offer(db, offer_id, lock=True)
    return await _acknowledge_disclosure(
        db=db,
        disclosure=disclosure,
        user=user,
        idempotency_key=idempotency_key,
        route=f"/admin/compliance/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
    )
