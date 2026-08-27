import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.financial_models import AccountingPeriod, JournalEntry, JournalPosting, LedgerAccount
from app.financial_schemas import JournalEntryCreate, TrialBalanceLine, TrialBalanceRead


def resolve_organization(principal: Principal, requested: uuid.UUID | None) -> uuid.UUID:
    selected = principal.active_organization_id
    if requested is not None and selected is not None and requested != selected:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ORGANIZATION_CONTEXT_MISMATCH",
                "message": "The requested organization does not match X-Organization-ID.",
            },
        )

    organization_id = requested or selected
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


def resolve_idempotency_key(body_key: str | None, header_key: str | None) -> str:
    body_key = body_key.strip() if body_key else None
    header_key = header_key.strip() if header_key else None
    if body_key and header_key and body_key != header_key:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IDEMPOTENCY_KEY_MISMATCH",
                "message": "Idempotency-Key must match the legacy body idempotency_key when both are supplied.",
            },
        )
    key = header_key or body_key
    if not key:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "Idempotency-Key is required for journal posting.",
            },
        )
    if len(key) < 8 or len(key) > 160:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_IDEMPOTENCY_KEY",
                "message": "Idempotency-Key must contain between 8 and 160 characters.",
            },
        )
    return key


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


async def _existing_journal(
    db: AsyncSession,
    organization_id: uuid.UUID,
    idempotency_key: str,
) -> tuple[JournalEntry, list[JournalPosting]] | None:
    existing = await db.scalar(
        select(JournalEntry).where(
            JournalEntry.organization_id == organization_id,
            JournalEntry.idempotency_key == idempotency_key,
        )
    )
    if existing is None:
        return None
    postings = list(
        (
            await db.scalars(
                select(JournalPosting)
                .where(JournalPosting.journal_entry_id == existing.id)
                .order_by(JournalPosting.created_at, JournalPosting.id)
            )
        ).all()
    )
    return existing, postings


async def post_journal(
    db: AsyncSession,
    principal: Principal,
    payload: JournalEntryCreate,
    *,
    idempotency_key: str | None = None,
) -> tuple[JournalEntry, list[JournalPosting]]:
    require_finance_permission(principal, "finance.post")
    organization_id = resolve_organization(principal, payload.organization_id)
    canonical_idempotency_key = resolve_idempotency_key(payload.idempotency_key, idempotency_key)

    existing = await _existing_journal(db, organization_id, canonical_idempotency_key)
    if existing is not None:
        return existing

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
        raise HTTPException(
            status_code=422,
            detail={"code": "ACCOUNT_NOT_FOUND", "message": "A ledger account was not found."},
        )
    for account in accounts:
        if account.organization_id != organization_id or not account.active:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "ACCOUNT_ACCESS_DENIED",
                    "message": "Ledger account is unavailable for this organization.",
                },
            )
        if account.currency != payload.currency:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "CURRENCY_MISMATCH",
                    "message": "Journal currency must match every ledger account.",
                },
            )

    period = await period_for_date(db, organization_id, payload.effective_at)
    if period is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ACCOUNTING_PERIOD_REQUIRED",
                "message": "An open accounting period must cover the journal effective date.",
            },
        )
    if period.status != "OPEN":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ACCOUNTING_PERIOD_CLOSED",
                "message": "The accounting period is closed or locked.",
            },
        )

    posted_at = datetime.now(UTC)
    entry = JournalEntry(
        organization_id=organization_id,
        period_id=period.id,
        entry_number=f"JE-{posted_at:%Y%m%d}-{uuid.uuid4().hex[:10].upper()}",
        idempotency_key=canonical_idempotency_key,
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

    postings: list[JournalPosting] = []
    try:
        db.add(entry)
        await db.flush()
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
    except IntegrityError:
        await db.rollback()
        existing = await _existing_journal(db, organization_id, canonical_idempotency_key)
        if existing is not None:
            return existing
        raise

    await db.refresh(entry)
    for posting in postings:
        await db.refresh(posting)
    return entry, postings


async def trial_balance(
    db: AsyncSession,
    principal: Principal,
    organization_id: uuid.UUID | None,
    as_of: datetime | None,
    currency: str | None = None,
) -> TrialBalanceRead:
    require_finance_permission(principal, "finance.read")
    organization_id = resolve_organization(principal, organization_id)
    as_of = as_of or datetime.now(UTC)

    all_accounts = list(
        (
            await db.scalars(
                select(LedgerAccount)
                .where(LedgerAccount.organization_id == organization_id)
                .order_by(LedgerAccount.code)
            )
        ).all()
    )
    available_currencies = sorted({account.currency for account in all_accounts})
    if currency is None:
        if len(available_currencies) > 1:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "CURRENCY_REQUIRED",
                    "message": "Select a currency when the chart of accounts contains multiple currencies.",
                    "context": {"currencies": available_currencies},
                },
            )
        currency = available_currencies[0] if available_currencies else "USD"
    currency = currency.strip().upper()

    accounts = [account for account in all_accounts if account.currency == currency]
    account_map = {account.id: account for account in accounts}
    totals = {account.id: [Decimal("0"), Decimal("0")] for account in accounts}

    if account_map:
        rows = (
            await db.execute(
                select(JournalPosting, JournalEntry)
                .join(JournalEntry, JournalEntry.id == JournalPosting.journal_entry_id)
                .where(
                    JournalEntry.organization_id == organization_id,
                    JournalEntry.currency == currency,
                    JournalEntry.status == "POSTED",
                    JournalEntry.effective_at <= as_of,
                    JournalPosting.account_id.in_(account_map),
                )
            )
        ).all()
        for posting, _entry in rows:
            if posting.side == "DEBIT":
                totals[posting.account_id][0] += posting.amount
            else:
                totals[posting.account_id][1] += posting.amount

    lines: list[TrialBalanceLine] = []
    debit_total = Decimal("0")
    credit_total = Decimal("0")
    for account_id, (debits, credits) in totals.items():
        account = account_map[account_id]
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
