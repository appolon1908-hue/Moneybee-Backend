from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from app.portal_models import ProviderWebhookReceipt
from app.webhook_gateway import (
    claim_provider_webhooks,
    complete_provider_webhook,
    fail_provider_webhook,
)


class ProviderWebhookHandler(Protocol):
    def __call__(self, db: Session, receipt: ProviderWebhookReceipt) -> None: ...


class ProviderTranslatorNotRegistered(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderHandlerKey:
    provider: str
    event_type: str


@dataclass(frozen=True)
class ProviderWebhookBatchResult:
    claimed: int
    processed: int
    retried: int
    dead_lettered: int


_HANDLERS: dict[ProviderHandlerKey, ProviderWebhookHandler] = {}


def register_provider_handler(
    provider: str,
    event_type: str,
    handler: ProviderWebhookHandler,
) -> None:
    normalized_provider = provider.strip().lower()
    normalized_event_type = event_type.strip()
    if not normalized_provider or not normalized_event_type:
        raise ValueError("provider and event_type are required")
    key = ProviderHandlerKey(normalized_provider, normalized_event_type)
    if key in _HANDLERS:
        raise ValueError(
            f"A provider webhook handler is already registered for {key.provider}:{key.event_type}"
        )
    _HANDLERS[key] = handler


def clear_provider_handlers() -> None:
    """Clear the in-process registry. Intended for deterministic tests only."""

    _HANDLERS.clear()


def resolve_provider_handler(
    provider: str,
    event_type: str,
) -> ProviderWebhookHandler | None:
    normalized_provider = provider.strip().lower()
    return _HANDLERS.get(
        ProviderHandlerKey(normalized_provider, event_type)
    ) or _HANDLERS.get(ProviderHandlerKey(normalized_provider, "*"))


def require_provider_handler(
    provider: str,
    event_type: str,
) -> ProviderWebhookHandler:
    handler = resolve_provider_handler(provider, event_type)
    if handler is None:
        raise ProviderTranslatorNotRegistered(
            f"No allowlisted translator is registered for {provider}:{event_type}"
        )
    return handler


def process_provider_webhook_batch(
    db: Session,
    *,
    worker_id: str,
    limit: int = 50,
) -> ProviderWebhookBatchResult:
    """Process a leased receipt batch through explicit provider translators.

    Intake and translation remain separate. A receipt without an allowlisted translator
    is retried and ultimately dead-lettered; it never falls through to a generic lending
    mutation.
    """

    receipts = claim_provider_webhooks(db, worker_id=worker_id, limit=limit)
    processed = 0
    retried = 0
    dead_lettered = 0

    for claimed in receipts:
        receipt_id = claimed.id
        try:
            handler = require_provider_handler(claimed.provider, claimed.event_type)
            handler(db, claimed)
            complete_provider_webhook(db, claimed)
            processed += 1
        except Exception as exc:  # worker boundary: persist deterministic retry evidence
            db.rollback()
            receipt = db.get(ProviderWebhookReceipt, receipt_id)
            if receipt is None:
                raise RuntimeError(
                    f"Claimed webhook receipt disappeared: {receipt_id}"
                ) from exc
            fail_provider_webhook(db, receipt, error=f"{type(exc).__name__}: {exc}")
            if receipt.status == "DEAD_LETTER":
                dead_lettered += 1
            else:
                retried += 1

    return ProviderWebhookBatchResult(
        claimed=len(receipts),
        processed=processed,
        retried=retried,
        dead_lettered=dead_lettered,
    )
