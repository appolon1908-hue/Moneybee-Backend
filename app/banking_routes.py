import hashlib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import banking, models, schemas, services
from app.auth import Principal, current_principal
from app.db import get_db
from app.integrations.base import ProviderError
from app.integrations.plaid import PlaidAdapter


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


def provider_http_error(exc: ProviderError) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={
            "code": "PROVIDER_REQUEST_FAILED",
            "provider": exc.provider,
            "message": "The configured provider could not complete the request.",
        },
    )


@router.post(
    "/applications/{application_id}/bank/link-session",
    tags=["banking"],
)
async def bank_link_session(
    application_id: uuid.UUID,
    db: Db,
    user: User,
):
    await services.require_capability(db, "bank.live_connection")
    application = await services.get_authorized_application(db, application_id, user, write=True)
    try:
        return await banking.create_link_session(application)
    except ProviderError as exc:
        raise provider_http_error(exc) from exc


@router.post(
    "/applications/{application_id}/bank/exchange",
    response_model=schemas.BankConnectionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["banking"],
)
async def bank_exchange(
    application_id: uuid.UUID,
    payload: schemas.BankExchangeInput,
    db: Db,
    user: User,
):
    await services.require_capability(db, "bank.live_connection")
    application = await services.get_authorized_application(db, application_id, user, write=True)
    try:
        connection = await banking.exchange_public_token(
            db,
            application,
            payload.public_token,
        )
    except ProviderError as exc:
        raise provider_http_error(exc) from exc
    await db.commit()
    await db.refresh(connection)
    return connection


@router.post(
    "/applications/{application_id}/bank/sync",
    tags=["banking"],
)
async def bank_sync(
    application_id: uuid.UUID,
    db: Db,
    user: User,
):
    await services.require_capability(db, "bank.live_connection")
    application = await services.get_authorized_application(db, application_id, user, write=True)
    try:
        result = await banking.sync_bank(db, application)
    except ProviderError as exc:
        raise provider_http_error(exc) from exc
    await db.commit()
    return result


@router.get(
    "/applications/{application_id}/bank/connections",
    response_model=list[schemas.BankConnectionRead],
    tags=["banking"],
)
async def bank_connections(
    application_id: uuid.UUID,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.BankConnection)
                .where(models.BankConnection.application_id == application_id)
                .order_by(models.BankConnection.created_at.desc())
            )
        ).all()
    )


@router.get(
    "/applications/{application_id}/bank/accounts",
    response_model=list[schemas.BankAccountRead],
    tags=["banking"],
)
async def bank_accounts(
    application_id: uuid.UUID,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.BankAccount)
                .join(
                    models.BankConnection,
                    models.BankConnection.id == models.BankAccount.connection_id,
                )
                .where(models.BankConnection.application_id == application_id)
                .order_by(models.BankAccount.name)
            )
        ).all()
    )


@router.get(
    "/applications/{application_id}/bank/analysis",
    response_model=schemas.BankAnalysisRead | None,
    tags=["banking"],
)
async def bank_analysis(
    application_id: uuid.UUID,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user)
    return await db.scalar(
        select(models.BankAnalysis)
        .where(models.BankAnalysis.application_id == application_id)
        .order_by(models.BankAnalysis.created_at.desc())
    )


@router.post("/webhooks/plaid", tags=["provider-webhooks"])
async def plaid_webhook(
    request: Request,
    db: Db,
    plaid_verification: Annotated[str | None, Header(alias="Plaid-Verification")] = None,
):
    await services.require_capability(db, "bank.live_connection")
    body = await request.body()
    adapter = PlaidAdapter()
    if not await adapter.verify_webhook(body, plaid_verification):
        raise HTTPException(status_code=401, detail="Invalid Plaid webhook")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook payload",
        ) from exc

    payload_hash = hashlib.sha256(body).hexdigest()
    event_code = str(payload.get("webhook_code") or payload.get("webhook_type") or "UNKNOWN")
    item_id = str(payload.get("item_id") or "unknown")
    provider_event_id = str(
        payload.get("webhook_id") or f"{item_id}:{event_code}:{payload_hash[:24]}"
    )
    existing = await db.scalar(
        select(models.WebhookReceipt).where(
            models.WebhookReceipt.provider == "plaid",
            models.WebhookReceipt.provider_event_id == provider_event_id,
        )
    )
    if existing is not None:
        return {"received": True, "duplicate": True}

    receipt = models.WebhookReceipt(
        provider="plaid",
        provider_event_id=provider_event_id,
        event_type=event_code,
        payload_hash=payload_hash,
        payload_metadata={
            "item_id": item_id,
            "webhook_code": event_code,
        },
        status="RECEIVED",
    )
    db.add(receipt)
    await db.flush()
    db.add(
        models.OutboxEvent(
            event_type="PlaidWebhookReceived",
            aggregate_id=receipt.id,
            payload={
                "receipt_id": str(receipt.id),
                "provider": "plaid",
                "event_type": event_code,
            },
            idempotency_key=f"PlaidWebhookReceived:{provider_event_id}",
        )
    )
    await db.commit()
    return {"received": True, "duplicate": False}
