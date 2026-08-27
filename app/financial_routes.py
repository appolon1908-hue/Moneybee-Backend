import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, current_principal
from app.db import get_db
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
from app.financial_service import (
    close_accounting_period,
    create_accounting_period,
    create_ledger_account,
    list_accounts,
    list_journal_entries,
    list_journal_postings,
    list_periods,
    post_journal,
    trial_balance,
)
from app.request_context import request_identifiers


router = APIRouter(prefix="/finance", tags=["finance"])
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=160),
]


@router.get("/accounts", response_model=list[LedgerAccountRead])
async def finance_accounts(
    db: Db,
    user: User,
    currency: Annotated[
        str | None,
        Query(min_length=3, max_length=3, pattern="^[A-Za-z]{3}$"),
    ] = None,
):
    return await list_accounts(db, user, currency)


@router.post("/accounts", response_model=LedgerAccountRead, status_code=201)
async def finance_create_account(
    payload: LedgerAccountCreate,
    request: Request,
    db: Db,
    user: User,
):
    identifiers = request_identifiers(request)
    return await create_ledger_account(
        db,
        user,
        payload,
        request_id=identifiers.request_id,
        correlation_id=identifiers.correlation_id,
    )


@router.get("/periods", response_model=list[AccountingPeriodRead])
async def finance_periods(db: Db, user: User):
    return await list_periods(db, user)


@router.post("/periods", response_model=AccountingPeriodRead, status_code=201)
async def finance_create_period(
    payload: AccountingPeriodCreate,
    request: Request,
    db: Db,
    user: User,
):
    identifiers = request_identifiers(request)
    return await create_accounting_period(
        db,
        user,
        payload,
        request_id=identifiers.request_id,
        correlation_id=identifiers.correlation_id,
    )


@router.post("/periods/{period_id}/close", response_model=AccountingPeriodRead)
async def finance_close_period(
    period_id: uuid.UUID,
    request: Request,
    db: Db,
    user: User,
):
    identifiers = request_identifiers(request)
    return await close_accounting_period(
        db,
        user,
        period_id,
        request_id=identifiers.request_id,
        correlation_id=identifiers.correlation_id,
    )


@router.post("/journal-entries", response_model=JournalEntryRead, status_code=201)
async def finance_create_journal_entry(
    payload: JournalEntryCreate,
    request: Request,
    response: Response,
    db: Db,
    user: User,
    idempotency_key: IdempotencyKey,
):
    identifiers = request_identifiers(request)
    entry, _postings, replayed = await post_journal(
        db,
        user,
        payload,
        idempotency_key=idempotency_key,
        request_id=identifiers.request_id,
        correlation_id=identifiers.correlation_id,
    )
    response.headers["X-Idempotent-Replay"] = "true" if replayed else "false"
    return entry


@router.get("/journal-entries", response_model=list[JournalEntryRead])
async def finance_journal_entries(
    db: Db,
    user: User,
    currency: Annotated[
        str | None,
        Query(min_length=3, max_length=3, pattern="^[A-Za-z]{3}$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    return await list_journal_entries(
        db,
        user,
        currency=currency,
        limit=limit,
    )


@router.get(
    "/journal-entries/{entry_id}/postings",
    response_model=list[PostingRead],
)
async def finance_journal_postings(
    entry_id: uuid.UUID,
    db: Db,
    user: User,
):
    return await list_journal_postings(db, user, entry_id)


@router.get("/trial-balance", response_model=TrialBalanceRead)
async def finance_trial_balance(
    db: Db,
    user: User,
    as_of: datetime | None = Query(default=None),
    currency: Annotated[
        str | None,
        Query(min_length=3, max_length=3, pattern="^[A-Za-z]{3}$"),
    ] = None,
):
    return await trial_balance(db, user, as_of, currency)
