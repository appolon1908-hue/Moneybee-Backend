from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.auth import Principal
from app.financial_models import (
    AccountingPeriod,
    JournalEntry,
    JournalPosting,
    LedgerAccount,
)
from app.financial_schemas import (
    AccountingPeriodCreate,
    JournalEntryCreate,
    LedgerAccountCreate,
    TrialBalanceLine,
    TrialBalanceRead,
)


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def active_organization(principal: Principal) -> uuid.UUID:
    organization_id = principal.active_organization_id
    if organization_id is None:
        raise _problem(
            "ORGANIZATION_REQUIRED",
            "Select an organization before using a tenant-scoped endpoint.",
            422,
        )
    if (
        "*" not in principal.permissions
        and organization_id not in principal.organization_ids
    ):
        raise _problem(
            "ORGANIZATION_ACCESS_DENIED",
            "The selected organization is not available to this principal.",
            403,
        )
    return organization_id


def require_finance_permission(principal: Principal, permission: str) -> None:
    if "*" not in principal.permissions and permission not in principal.permissions:
        raise _problem(
            "PERMISSION_DENIED",
            f"{permission} is required.",
            403,
        )


def validate_idempotency_key(value: str) -> str:
    key = value.strip()
    if len(key) < 8 or len(key) > 160:
        raise _problem(
            "INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key must contain between 8 and 160 characters.",
            400,
        )
    return key


def journal_request_hash(payload: JournalEntryCreate) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _audit(
    *,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    request_id: str,
    correlation_id: str,
    details: dict,
) -> models.AuditEvent:
    return models.AuditEvent(
        actor_id=principal.subject,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        request_id=request_id,
        details={
            **details,
            "organization_id": str(principal.active_organization_id),
            "correlation_id": correlation_id,
        },
    )


def _outbox(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    organization_id: uuid.UUID,
    request_id: str,
    correlation_id: str,
    payload: dict,
    aggregate_version: int | None = None,
) -> models.OutboxEvent:
    return models.OutboxEvent(
        event_type=event_type,
        schema_version=1,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        tenant_id=str(organization_id),
        correlation_id=correlation_id,
        causation_id=request_id,
        payload=payload,
        idempotency_key=f"{event_type}:{aggregate_id}:{aggregate_version or 1}",
    )


async def list_accounts(
    db: AsyncSession,
    principal: Principal,
    currency: str | None,
) -> list[LedgerAccount]:
    require_finance_permission(principal, "finance.read")
    organization_id = active_organization(principal)
    statement = select(LedgerAccount).where(
        LedgerAccount.organization_id == organization_id
    )
    if currency:
        statement = statement.where(LedgerAccount.currency == currency.upper())
    return list((await db.scalars(statement.order_by(LedgerAccount.code))).all())


async def create_ledger_account(
    db: AsyncSession,
    principal: Principal,
    payload: LedgerAccountCreate,
    *,
    request_id: str,
    correlation_id: str,
) -> LedgerAccount:
    require_finance_permission(principal, "finance.manage")
    organization_id = active_organization(principal)
    normalized_code = payload.code.strip().upper()
    existing = await db.scalar(
        select(LedgerAccount).where(
            LedgerAccount.organization_id == organization_id,
            LedgerAccount.code == normalized_code,
        )
    )
    if existing:
        raise _problem(
            "ACCOUNT_CODE_EXISTS",
            "Ledger account code already exists.",
            409,
        )

    item = LedgerAccount(
        organization_id=organization_id,
        code=normalized_code,
        name=payload.name.strip(),
        account_type=payload.account_type,
        currency=payload.currency,
    )
    db.add(item)
    await db.flush()
    db.add_all(
        [
            _audit(
                principal=principal,
                action="FINANCE_LEDGER_ACCOUNT_CREATED",
                resource_type="ledger_account",
                resource_id=item.id,
                request_id=request_id,
                correlation_id=correlation_id,
                details={
                    "code": item.code,
                    "account_type": item.account_type,
                    "currency": item.currency,
                },
            ),
            _outbox(
                event_type="FinanceLedgerAccountCreated",
                aggregate_type="ledger_account",
                aggregate_id=item.id,
                organization_id=organization_id,
                request_id=request_id,
                correlation_id=correlation_id,
                payload={
                    "ledger_account_id": str(item.id),
                    "organization_id": str(organization_id),
                    "code": item.code,
                    "account_type": item.account_type,
                    "currency": item.currency,
                },
            ),
        ]
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _problem(
            "ACCOUNT_CODE_EXISTS",
            "Ledger account code already exists.",
            409,
        ) from exc
    await db.refresh(item)
    return item


async def list_periods(
    db: AsyncSession,
    principal: Principal,
) -> list[AccountingPeriod]:
    require_finance_permission(principal, "finance.read")
    organization_id = active_organization(principal)
    return list(
        (
            await db.scalars(
                select(AccountingPeriod)
                .where(AccountingPeriod.organization_id == organization_id)
                .order_by(AccountingPeriod.starts_at.desc())
            )
        ).all()
    )


async def create_accounting_period(
    db: AsyncSession,
    principal: Principal,
    payload: AccountingPeriodCreate,
    *,
    request_id: str,
    correlation_id: str,
) -> AccountingPeriod:
    require_finance_permission(principal, "finance.manage")
    organization_id = active_organization(principal)
    overlap = await db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.organization_id == organization_id,
            AccountingPeriod.starts_at < payload.ends_at,
            AccountingPeriod.ends_at > payload.starts_at,
        )
    )
    if overlap:
        raise _problem(
            "ACCOUNTING_PERIOD_OVERLAP",
            "Accounting periods may not overlap.",
            409,
        )

    item = AccountingPeriod(
        organization_id=organization_id,
        name=payload.name.strip(),
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        status="OPEN",
    )
    db.add(item)
    await db.flush()
    db.add_all(
        [
            _audit(
                principal=principal,
                action="FINANCE_PERIOD_CREATED",
                resource_type="accounting_period",
                resource_id=item.id,
                request_id=request_id,
                correlation_id=correlation_id,
                details={
                    "name": item.name,
                    "starts_at": item.starts_at.isoformat(),
                    "ends_at": item.ends_at.isoformat(),
                },
            ),
            _outbox(
                event_type="FinanceAccountingPeriodCreated",
                aggregate_type="accounting_period",
                aggregate_id=item.id,
                organization_id=organization_id,
                request_id=request_id,
                correlation_id=correlation_id,
                payload={
                    "period_id": str(item.id),
                    "organization_id": str(organization_id),
                    "name": item.name,
                    "starts_at": item.starts_at.isoformat(),
                    "ends_at": item.ends_at.isoformat(),
                },
            ),
        ]
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _problem(
            "ACCOUNTING_PERIOD_EXISTS",
            "An accounting period with this name already exists.",
            409,
        ) from exc
    await db.refresh(item)
    return item


async def close_accounting_period(
    db: AsyncSession,
    principal: Principal,
    period_id: uuid.UUID,
    *,
    request_id: str,
    correlation_id: str,
) -> AccountingPeriod:
    require_finance_permission(principal, "finance.manage")
    organization_id = active_organization(principal)
    period = await db.scalar(
        select(AccountingPeriod)
        .where(
            AccountingPeriod.id == period_id,
            AccountingPeriod.organization_id == organization_id,
        )
        .with_for_update()
    )
    if period is None:
        raise HTTPException(status_code=404, detail="Accounting period not found")
    if period.status != "OPEN":
        raise _problem(
            "PERIOD_NOT_OPEN",
            "Only an open accounting period can be closed.",
            409,
        )

    period.status = "CLOSED"
    period.closed_at = datetime.now(UTC)
    period.closed_by = principal.subject
    db.add_all(
        [
            _audit(
                principal=principal,
                action="FINANCE_PERIOD_CLOSED",
                resource_type="accounting_period",
                resource_id=period.id,
                request_id=request_id,
                correlation_id=correlation_id,
                details={"status": period.status},
            ),
            _outbox(
                event_type="FinanceAccountingPeriodClosed",
                aggregate_type="accounting_period",
                aggregate_id=period.id,
                organization_id=organization_id,
                request_id=request_id,
                correlation_id=correlation_id,
                payload={
                    "period_id": str(period.id),
                    "organization_id": str(organization_id),
                    "status": period.status,
                    "closed_at": period.closed_at.isoformat(),
                },
            ),
        ]
    )
    await db.commit()
    await db.refresh(period)
    return period


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
    request_hash: str,
) -> tuple[JournalEntry, list[JournalPosting]] | None:
    existing = await db.scalar(
        select(JournalEntry).where(
            JournalEntry.organization_id == organization_id,
            JournalEntry.idempotency_key == idempotency_key,
        )
    )
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise _problem(
            "IDEMPOTENCY_CONFLICT",
            "The Idempotency-Key was already used with a different journal command.",
            409,
        )
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
    idempotency_key: str,
    request_id: str,
    correlation_id: str,
) -> tuple[JournalEntry, list[JournalPosting], bool]:
    require_finance_permission(principal, "finance.post")
    organization_id = active_organization(principal)
    canonical_idempotency_key = validate_idempotency_key(idempotency_key)
    request_hash = journal_request_hash(payload)

    existing = await _existing_journal(
        db,
        organization_id,
        canonical_idempotency_key,
        request_hash,
    )
    if existing is not None:
        return existing[0], existing[1], True

    debit_total = sum(
        (posting.amount for posting in payload.postings if posting.side == "DEBIT"),
        Decimal("0"),
    )
    credit_total = sum(
        (posting.amount for posting in payload.postings if posting.side == "CREDIT"),
        Decimal("0"),
    )
    if debit_total != credit_total or debit_total <= 0:
        raise _problem(
            "UNBALANCED_JOURNAL",
            "Debits and credits must balance.",
            422,
        )

    account_ids = {posting.account_id for posting in payload.postings}
    accounts = list(
        (
            await db.scalars(
                select(LedgerAccount).where(LedgerAccount.id.in_(account_ids))
            )
        ).all()
    )
    if len(accounts) != len(account_ids):
        raise _problem(
            "ACCOUNT_NOT_FOUND",
            "A ledger account was not found.",
            422,
        )
    for account in accounts:
        if account.organization_id != organization_id or not account.active:
            raise _problem(
                "ACCOUNT_ACCESS_DENIED",
                "Ledger account is unavailable for this organization.",
                403,
            )
        if account.currency != payload.currency:
            raise _problem(
                "CURRENCY_MISMATCH",
                "Journal currency must match every ledger account.",
                422,
            )

    period = await period_for_date(db, organization_id, payload.effective_at)
    if period is None:
        raise _problem(
            "ACCOUNTING_PERIOD_REQUIRED",
            "An open accounting period must cover the journal effective date.",
            409,
        )
    if period.status != "OPEN":
        raise _problem(
            "ACCOUNTING_PERIOD_CLOSED",
            "The accounting period is closed or locked.",
            409,
        )

    posted_at = datetime.now(UTC)
    entry = JournalEntry(
        organization_id=organization_id,
        period_id=period.id,
        entry_number=f"JE-{posted_at:%Y%m%d}-{uuid.uuid4().hex[:10].upper()}",
        idempotency_key=canonical_idempotency_key,
        request_hash=request_hash,
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

        db.add_all(
            [
                _audit(
                    principal=principal,
                    action="FINANCE_JOURNAL_POSTED",
                    resource_type="journal_entry",
                    resource_id=entry.id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    details={
                        "entry_number": entry.entry_number,
                        "source_type": entry.source_type,
                        "source_id": entry.source_id,
                        "currency": entry.currency,
                        "debit_total": str(debit_total),
                        "credit_total": str(credit_total),
                        "idempotency_key": canonical_idempotency_key,
                        "request_hash": request_hash,
                    },
                ),
                _outbox(
                    event_type="FinanceJournalPosted",
                    aggregate_type="journal_entry",
                    aggregate_id=entry.id,
                    organization_id=organization_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    payload={
                        "journal_entry_id": str(entry.id),
                        "organization_id": str(organization_id),
                        "entry_number": entry.entry_number,
                        "source_type": entry.source_type,
                        "source_id": entry.source_id,
                        "currency": entry.currency,
                        "effective_at": entry.effective_at.isoformat(),
                        "debit_total": str(debit_total),
                        "credit_total": str(credit_total),
                    },
                ),
            ]
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await _existing_journal(
            db,
            organization_id,
            canonical_idempotency_key,
            request_hash,
        )
        if existing is not None:
            return existing[0], existing[1], True
        raise

    await db.refresh(entry)
    for posting in postings:
        await db.refresh(posting)
    return entry, postings, False


async def list_journal_entries(
    db: AsyncSession,
    principal: Principal,
    *,
    currency: str | None,
    limit: int,
) -> list[JournalEntry]:
    require_finance_permission(principal, "finance.read")
    organization_id = active_organization(principal)
    statement = select(JournalEntry).where(
        JournalEntry.organization_id == organization_id
    )
    if currency:
        statement = statement.where(JournalEntry.currency == currency.upper())
    return list(
        (
            await db.scalars(
                statement
                .order_by(
                    JournalEntry.effective_at.desc(),
                    JournalEntry.created_at.desc(),
                )
                .limit(limit)
            )
        ).all()
    )


async def list_journal_postings(
    db: AsyncSession,
    principal: Principal,
    entry_id: uuid.UUID,
) -> list[JournalPosting]:
    require_finance_permission(principal, "finance.read")
    organization_id = active_organization(principal)
    entry = await db.scalar(
        select(JournalEntry).where(
            JournalEntry.id == entry_id,
            JournalEntry.organization_id == organization_id,
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return list(
        (
            await db.scalars(
                select(JournalPosting)
                .where(JournalPosting.journal_entry_id == entry_id)
                .order_by(JournalPosting.created_at, JournalPosting.id)
            )
        ).all()
    )


async def trial_balance(
    db: AsyncSession,
    principal: Principal,
    as_of: datetime | None,
    currency: str | None = None,
) -> TrialBalanceRead:
    require_finance_permission(principal, "finance.read")
    organization_id = active_organization(principal)
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
            raise _problem(
                "CURRENCY_REQUIRED",
                "Select a currency when the chart of accounts contains multiple currencies.",
                422,
            )
        currency = available_currencies[0] if available_currencies else "USD"
    currency = currency.strip().upper()

    accounts = [account for account in all_accounts if account.currency == currency]
    account_map = {account.id: account for account in accounts}
    totals = {
        account.id: [Decimal("0"), Decimal("0")]
        for account in accounts
    }

    if account_map:
        rows = (
            await db.execute(
                select(JournalPosting, JournalEntry)
                .join(
                    JournalEntry,
                    JournalEntry.id == JournalPosting.journal_entry_id,
                )
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
