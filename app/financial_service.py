import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.financial_models import AccountingPeriod, JournalEntry, JournalPosting, LedgerAccount
from app.financial_schemas import JournalEntryCreate, TrialBalanceLine, TrialBalanceRead


def resolve_organization(principal: Principal, requested: uuid.UUID | None) -> uuid.UUID:
    organization_id = requested or principal.active_organization_id
    if organization_id is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "ORGANIZATION_REQUIRED", "message": "Select an organization first."},
        )
    if "*" not in principal.permissions and organization_id not in principal.organization_ids:
        raise HTTPException(
            status_code=403,
            detail={"code": "ORGANIZATION_ACCESS_DENIED", "message": "Organization access denied."},
        )
    return organization_id


def require_finance_permission(principal: Principal, permission: str) -> None:
    if "*" not in principal.permissions and permission not in principal.permissions:
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": f"{permission} is required."},
        )


async def period_for_date(
    db: AsyncSession,
    organization_id: uuid.UUID,
    effective_at: datetime,
) -> AccountingPeriod | None:
    return await db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.organization_id == organization_id,
            AccountingPeriod.starts_at <= effective_at,
            AccountingPeriod.ends_at > effective_at,
        )
    )


async def post_journal(
    db: AsyncSession,
    principal: Principal,
    payload: JournalEntryCreate,
) -> tuple[JournalEntry, list[JournalPosting]]:
    require_finance_permission(principal, "finance.post")
    organization_id = resolve_organization(principal, payload.organization_id)

    existing = await db.scalar(
        select(JournalEntry).where(
            JournalEntry.organization_id == organization_id,
            JournalEntry.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        postings = list(
            (
                await db.scalars(
                    select(JournalPosting).where(JournalPosting.journal_entry_id == existing.id)
                )
            ).all()
        )
        return existing, postings

    debit_total = sum((p.amount for p in payload.postings if p.side == "DEBIT"), Decimal("0"))
    credit_total = sum((p.amount for p in payload.postings if p.side == "CREDIT"), Decimal("0"))
    if debit_total != credit_total or debit_total <= 0:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNBALANCED_JOURNAL", "message": "Debits and credits must balance."},
        )

    account_ids = {posting.account_id for posting in payload.postings}
    accounts = list((await db.scalars(select(LedgerAccount).where(LedgerAccount.id.in_(account_ids)))).all())
    if len(accounts) != len(account_ids):
        raise HTTPException(status_code=422, detail={"code": "ACCOUNT_NOT_FOUND", "message": "A ledger account was not found."})
    for account in accounts:
        if account.organization_id != organization_id or not account.active:
            raise HTTPException(status_code=403, detail={"code": "ACCOUNT_ACCESS_DENIED", "message": "Ledger account is unavailable for this organization."})
        if account.currency != payload.currency:
            raise HTTPException(status_code=422, detail={"code": "CURRENCY_MISMATCH", "message": "Journal currency must match every ledger account."})

    period = await period_for_date(db, organization_id, payload.effective_at)
    if period and period.status != "OPEN":
        raise HTTPException(status_code=409, detail={"code": "ACCOUNTING_PERIOD_CLOSED", "message": "The accounting period is closed or locked."})

    posted_at = datetime.now(UTC)
    entry = JournalEntry(
        organization_id=organization_id,
        period_id=period.id if period else None,
        entry_number=f"JE-{posted_at:%Y%m%d}-{uuid.uuid4().hex[:10].upper()}",
        idempotency_key=payload.idempotency_key,
        source_type=payload.source_type,
        source_id=payload.source_id,
        description=payload.description,
        currency=payload.currency,
        effective_at=payload.effective_at,
        status="POSTED",
        posted_at=posted_at,
        posted_by=principal.subject,
        metadata_payload=payload.metadata_payload,
    )
    db.add(entry)
    await db.flush()

    postings: list[JournalPosting] = []
    for item in payload.postings:
        posting = JournalPosting(
            journal_entry_id=entry.id,
            account_id=item.account_id,
            side=item.side,
            amount=item.amount,
            currency=payload.currency,
            application_id=item.application_id,
            funding_id=item.funding_id,
            commission_id=item.commission_id,
            bank_transaction_id=item.bank_transaction_id,
            memo=item.memo,
            metadata_payload=item.metadata_payload,
        )
        db.add(posting)
        postings.append(posting)

    await db.commit()
    await db.refresh(entry)
    for posting in postings:
        await db.refresh(posting)
    return entry, postings


async def trial_balance(
    db: AsyncSession,
    principal: Principal,
    organization_id: uuid.UUID | None,
    as_of: datetime | None,
) -> TrialBalanceRead:
    require_finance_permission(principal, "finance.read")
    organization_id = resolve_organization(principal, organization_id)
    as_of = as_of or datetime.now(UTC)

    accounts = list(
        (
            await db.scalars(
                select(LedgerAccount)
                .where(LedgerAccount.organization_id == organization_id)
                .order_by(LedgerAccount.code)
            )
        ).all()
    )
    account_map = {account.id: account for account in accounts}
    totals = {account.id: [Decimal("0"), Decimal("0")] for account in accounts}

    rows = (
        await db.execute(
            select(JournalPosting, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalPosting.journal_entry_id)
            .where(
                JournalEntry.organization_id == organization_id,
                JournalEntry.status == "POSTED",
                JournalEntry.effective_at <= as_of,
            )
        )
    ).all()
    for posting, _entry in rows:
        if posting.account_id not in totals:
            continue
        if posting.side == "DEBIT":
            totals[posting.account_id][0] += posting.amount
        else:
            totals[posting.account_id][1] += posting.amount

    lines: list[TrialBalanceLine] = []
    debit_total = Decimal("0")
    credit_total = Decimal("0")
    currency = "USD"
    for account_id, (debits, credits) in totals.items():
        account = account_map[account_id]
        currency = account.currency
        debit_total += debits
        credit_total += credits
        lines.append(
            TrialBalanceLine(
                account_id=account.id,
                code=account.code,
                name=account.name,
                account_type=account.account_type,
                debit_total=debits,
                credit_total=credits,
                balance=debits - credits,
            )
        )

    return TrialBalanceRead(
        organization_id=organization_id,
        currency=currency,
        as_of=as_of,
        debit_total=debit_total,
        credit_total=credit_total,
        balanced=debit_total == credit_total,
        accounts=lines,
    )
