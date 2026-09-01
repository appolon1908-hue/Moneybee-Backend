from datetime import UTC, datetime, timedelta
from decimal import Decimal
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.integrations.base import ProviderError
from app.integrations.registry import bank_adapter, credential_store


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(value + "T00:00:00+00:00")
        except ValueError:
            return None


async def create_link_session(application: models.Application) -> dict:
    return await bank_adapter().create_link_session(str(application.id))


async def exchange_public_token(
    db: AsyncSession,
    application: models.Application,
    public_token: str,
) -> models.BankConnection:
    adapter = bank_adapter()
    existing = await db.scalar(
        select(models.BankConnection).where(
            models.BankConnection.application_id == application.id,
            models.BankConnection.provider == adapter.name,
            models.BankConnection.status == "CONNECTED",
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="An active bank connection already exists",
        )

    result = await adapter.exchange_public_token(public_token)
    access_token = str(result.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "PROVIDER_REQUEST_FAILED",
                "provider": adapter.name,
                "message": "The bank provider did not return an access token.",
            },
        )
    try:
        credential_reference = await credential_store().store(access_token)
    except ProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "BANK_CREDENTIAL_STORE_UNAVAILABLE",
                "message": (
                    "The external bank credential store is unavailable; "
                    "MoneyBee does not store provider access tokens directly."
                ),
            },
        ) from exc
    connection = models.BankConnection(
        application_id=application.id,
        provider=adapter.name,
        provider_reference=result.get("item_id"),
        status="CONNECTED",
    )
    db.add(connection)
    await db.flush()
    db.add(
        models.BankProviderState(
            connection_id=connection.id,
            provider=adapter.name,
            item_id=result.get("item_id"),
            credential_reference=credential_reference,
            metadata_payload={"request_id": result.get("request_id")},
        )
    )
    db.add(
        models.OutboxEvent(
            event_type="BankConnectionCreated",
            aggregate_id=application.id,
            payload={
                "application_id": str(application.id),
                "connection_id": str(connection.id),
                "provider": adapter.name,
            },
            idempotency_key=f"BankConnectionCreated:{connection.id}",
        )
    )
    await db.flush()
    return connection


async def _connection(
    db: AsyncSession,
    application_id: uuid.UUID,
) -> models.BankConnection:
    connection = await db.scalar(
        select(models.BankConnection)
        .where(
            models.BankConnection.application_id == application_id,
            models.BankConnection.status == "CONNECTED",
        )
        .order_by(models.BankConnection.created_at.desc())
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Bank connection not found")
    return connection


async def sync_bank(
    db: AsyncSession,
    application: models.Application,
) -> dict:
    adapter = bank_adapter()
    connection = await _connection(db, application.id)
    if connection.provider != adapter.name:
        raise HTTPException(
            status_code=409,
            detail="Configured bank provider does not match the connection",
        )
    state = await db.scalar(
        select(models.BankProviderState).where(
            models.BankProviderState.connection_id == connection.id
        )
    )
    if state is None:
        raise HTTPException(status_code=409, detail="Bank provider state is missing")

    try:
        access_token = await credential_store().resolve(state.credential_reference)
    except ProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "BANK_CREDENTIAL_STORE_UNAVAILABLE",
                "message": "The external bank credential reference could not be resolved.",
            },
        ) from exc
    account_result = await adapter.get_accounts(access_token)
    account_map: dict[str, models.BankAccount] = {}
    for source in account_result.get("accounts", []):
        provider_account_id = str(source["account_id"])
        account = await db.scalar(
            select(models.BankAccount).where(
                models.BankAccount.connection_id == connection.id,
                models.BankAccount.provider_account_id == provider_account_id,
            )
        )
        balances = source.get("balances") or {}
        values = {
            "name": str(source.get("name") or "Bank account"),
            "official_name": source.get("official_name"),
            "mask": source.get("mask"),
            "account_type": source.get("type"),
            "subtype": source.get("subtype"),
            "current_balance": _decimal(balances.get("current")),
            "available_balance": _decimal(balances.get("available")),
            "currency": (
                balances.get("iso_currency_code")
                or balances.get("unofficial_currency_code")
            ),
            "active": True,
        }
        if account is None:
            account = models.BankAccount(
                connection_id=connection.id,
                provider_account_id=provider_account_id,
                **values,
            )
            db.add(account)
            await db.flush()
        else:
            for name, value in values.items():
                setattr(account, name, value)
        account_map[provider_account_id] = account
        db.add(
            models.BankBalanceSnapshot(
                account_id=account.id,
                current_balance=account.current_balance,
                available_balance=account.available_balance,
                currency=account.currency,
            )
        )

    transaction_result = await adapter.sync_transactions(
        access_token,
        state.transaction_cursor,
    )
    changed = 0
    for source in [
        *transaction_result.get("added", []),
        *transaction_result.get("modified", []),
    ]:
        transaction_id = str(source["transaction_id"])
        transaction = await db.scalar(
            select(models.BankTransaction).where(
                models.BankTransaction.provider == adapter.name,
                models.BankTransaction.provider_transaction_id
                == transaction_id,
            )
        )
        account = account_map.get(str(source.get("account_id")))
        posted_at = _date(source.get("date"))
        if posted_at is None:
            continue
        values = {
            "connection_id": connection.id,
            "account_id": account.id if account else None,
            "posted_at": posted_at,
            "authorized_at": _date(
                source.get("authorized_datetime")
                or source.get("authorized_date")
            ),
            "name": str(source.get("name") or "Transaction"),
            "merchant_name": source.get("merchant_name"),
            "amount": _decimal(source.get("amount")) or Decimal("0"),
            "currency": (
                source.get("iso_currency_code")
                or source.get("unofficial_currency_code")
            ),
            "pending": bool(source.get("pending", False)),
            "removed": False,
            "categories": list(source.get("category") or []),
            "metadata_payload": {
                "payment_channel": source.get("payment_channel"),
                "transaction_type": source.get("transaction_type"),
            },
        }
        if transaction is None:
            transaction = models.BankTransaction(
                provider=adapter.name,
                provider_transaction_id=transaction_id,
                **values,
            )
            db.add(transaction)
        else:
            for name, value in values.items():
                setattr(transaction, name, value)
        changed += 1

    for source in transaction_result.get("removed", []):
        transaction = await db.scalar(
            select(models.BankTransaction).where(
                models.BankTransaction.provider == adapter.name,
                models.BankTransaction.provider_transaction_id
                == str(source.get("transaction_id")),
            )
        )
        if transaction is not None:
            transaction.removed = True
            changed += 1

    state.transaction_cursor = transaction_result.get("next_cursor")
    analysis = await calculate_analysis(db, application.id, account_map.values())
    await db.flush()
    return {
        "connection_id": str(connection.id),
        "accounts": len(account_map),
        "transactions_changed": changed,
        "analysis_id": str(analysis.id),
    }


async def calculate_analysis(
    db: AsyncSession,
    application_id: uuid.UUID,
    accounts,
) -> models.BankAnalysis:
    cutoff = datetime.now(UTC) - timedelta(days=90)
    transactions = list(
        (
            await db.scalars(
                select(models.BankTransaction).where(
                    models.BankTransaction.connection_id.in_(
                        select(models.BankConnection.id).where(
                            models.BankConnection.application_id
                            == application_id
                        )
                    ),
                    models.BankTransaction.posted_at >= cutoff,
                    models.BankTransaction.removed.is_(False),
                    models.BankTransaction.pending.is_(False),
                )
            )
        ).all()
    )
    deposits = [-row.amount for row in transactions if row.amount < 0]
    nsf_count = sum(
        any(token in (row.name or "").upper() for token in ("NSF", "OVERDRAFT"))
        for row in transactions
    )
    balances = [
        row.current_balance
        for row in accounts
        if row.current_balance is not None
    ]
    risk_flags: list[str] = []
    if nsf_count >= 6:
        risk_flags.append("HIGH_NSF_ACTIVITY")
    if balances and min(balances) < 0:
        risk_flags.append("NEGATIVE_CURRENT_BALANCE")

    recent_total = sum(
        -row.amount
        for row in transactions
        if row.amount < 0
        and row.posted_at >= datetime.now(UTC) - timedelta(days=30)
    )
    previous_total = sum(
        -row.amount
        for row in transactions
        if row.amount < 0
        and datetime.now(UTC) - timedelta(days=60)
        <= row.posted_at
        < datetime.now(UTC) - timedelta(days=30)
    )
    trend = "STABLE"
    if previous_total > 0:
        change = (recent_total - previous_total) / previous_total
        if change >= Decimal("0.10"):
            trend = "GROWING"
        elif change <= Decimal("-0.10"):
            trend = "DECLINING"

    analysis = models.BankAnalysis(
        application_id=application_id,
        analysis_version=2,
        average_monthly_deposits=(
            sum(deposits, Decimal("0")) / Decimal("3") if deposits else None
        ),
        average_daily_balance=(
            sum(balances, Decimal("0")) / Decimal(len(balances))
            if balances
            else None
        ),
        negative_balance_days_90d=0,
        nsf_count_90d=nsf_count,
        deposit_count_90d=len(deposits),
        largest_deposit_90d=max(deposits) if deposits else None,
        revenue_trend=trend,
        cash_flow_trend=trend,
        risk_flags=risk_flags,
    )
    db.add(analysis)
    await db.flush()
    return analysis
