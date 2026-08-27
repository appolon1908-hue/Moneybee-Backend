import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, current_principal
from app.db import get_db
from app.financial_models import AccountingPeriod, JournalEntry, JournalPosting, LedgerAccount
from app.financial_schemas import (
    AccountingPeriodCreate,
    AccountingPeriodRead,
    JournalEntryCreate,
    JournalEntryRead,
    LedgerAccountCreate,
    LedgerAccountRead,
    PostingRead,
    TrialBalanceRead,
)
from app.financial_service import post_journal, require_finance_permission, resolve_organization, trial_balance
from app.models import utcnow


router = APIRouter(prefix="/finance", tags=["finance"])
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


@router.get("/accounts", response_model=list[LedgerAccountRead])
async def list_accounts(
    db: Db,
    user: User,
    organization_id: uuid.UUID | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3, pattern="^[A-Za-z]{3}$"),
):
    require_finance_permission(user, "finance.read")
    organization_id = resolve_organization(user, organization_id)
    statement = select(LedgerAccount).where(LedgerAccount.organization_id == organization_id)
    if currency:
        statement = statement.where(LedgerAccount.currency == currency.upper())
    return list((await db.scalars(statement.order_by(LedgerAccount.code))).all())


@router.post("/accounts", response_model=LedgerAccountRead, status_code=201)
async def create_account(payload: LedgerAccountCreate, db: Db, user: User):
    require_finance_permission(user, "finance.manage")
    organization_id = resolve_organization(user, payload.organization_id)
    normalized_code = payload.code.strip().upper()
    existing = await db.scalar(
        select(LedgerAccount).where(
            LedgerAccount.organization_id == organization_id,
            LedgerAccount.code == normalized_code,
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "ACCOUNT_CODE_EXISTS", "message": "Ledger account code already exists."},
        )
    item = LedgerAccount(
        organization_id=organization_id,
        code=normalized_code,
        name=payload.name.strip(),
        account_type=payload.account_type,
        currency=payload.currency,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/periods", response_model=list[AccountingPeriodRead])
async def list_periods(
    db: Db,
    user: User,
    organization_id: uuid.UUID | None = Query(default=None),
):
    require_finance_permission(user, "finance.read")
    organization_id = resolve_organization(user, organization_id)
    return list(
        (
            await db.scalars(
                select(AccountingPeriod)
                .where(AccountingPeriod.organization_id == organization_id)
                .order_by(AccountingPeriod.starts_at.desc())
            )
        ).all()
    )


@router.post("/periods", response_model=AccountingPeriodRead, status_code=201)
async def create_period(payload: AccountingPeriodCreate, db: Db, user: User):
    require_finance_permission(user, "finance.manage")
    organization_id = resolve_organization(user, payload.organization_id)
    overlap = await db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.organization_id == organization_id,
            AccountingPeriod.starts_at < payload.ends_at,
            AccountingPeriod.ends_at > payload.starts_at,
        )
    )
    if overlap:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ACCOUNTING_PERIOD_OVERLAP",
                "message": "Accounting periods may not overlap.",
            },
        )
    item = AccountingPeriod(
        organization_id=organization_id,
        name=payload.name.strip(),
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        status="OPEN",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/periods/{period_id}/close", response_model=AccountingPeriodRead)
async def close_period(period_id: uuid.UUID, db: Db, user: User):
    require_finance_permission(user, "finance.manage")
    period = await db.get(AccountingPeriod, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Accounting period not found")
    resolve_organization(user, period.organization_id)
    if period.status != "OPEN":
        raise HTTPException(
            status_code=409,
            detail={"code": "PERIOD_NOT_OPEN", "message": "Only an open accounting period can be closed."},
        )
    period.status = "CLOSED"
    period.closed_at = utcnow()
    period.closed_by = user.subject
    await db.commit()
    await db.refresh(period)
    return period


@router.post("/journal-entries", response_model=JournalEntryRead, status_code=201)
async def create_journal_entry(
    payload: JournalEntryCreate,
    db: Db,
    user: User,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    entry, _postings = await post_journal(
        db,
        user,
        payload,
        idempotency_key=idempotency_key,
    )
    return entry


@router.get("/journal-entries", response_model=list[JournalEntryRead])
async def list_journal_entries(
    db: Db,
    user: User,
    organization_id: uuid.UUID | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3, pattern="^[A-Za-z]{3}$"),
    limit: int = Query(default=100, ge=1, le=500),
):
    require_finance_permission(user, "finance.read")
    organization_id = resolve_organization(user, organization_id)
    statement = select(JournalEntry).where(JournalEntry.organization_id == organization_id)
    if currency:
        statement = statement.where(JournalEntry.currency == currency.upper())
    return list(
        (
            await db.scalars(
                statement
                .order_by(JournalEntry.effective_at.desc(), JournalEntry.created_at.desc())
                .limit(limit)
            )
        ).all()
    )


@router.get("/journal-entries/{entry_id}/postings", response_model=list[PostingRead])
async def journal_postings(entry_id: uuid.UUID, db: Db, user: User):
    require_finance_permission(user, "finance.read")
    entry = await db.get(JournalEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    resolve_organization(user, entry.organization_id)
    return list(
        (
            await db.scalars(
                select(JournalPosting)
                .where(JournalPosting.journal_entry_id == entry_id)
                .order_by(JournalPosting.created_at, JournalPosting.id)
            )
        ).all()
    )


@router.get("/trial-balance", response_model=TrialBalanceRead)
async def get_trial_balance(
    db: Db,
    user: User,
    organization_id: uuid.UUID | None = Query(default=None),
    as_of: datetime | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3, pattern="^[A-Za-z]{3}$"),
):
    return await trial_balance(db, user, organization_id, as_of, currency)
