from __future__ import annotations

import re
from typing import Any


SOURCE_URN = "urn:codestra:moneybee-backend"
PUBLIC_TENANT_SCOPE = "public"
INTERNAL_ACTOR_KEY = "_event_actor"
INTERNAL_SUBJECT_KEY = "_event_subject"

_CANONICAL_ALIASES = {
    "LeadSubmitted": "codestra.moneybee.lead.created.v1",
    "BankWebhookReceived": "codestra.moneybee.bank.provider_event_received.v1",
    "PlaidWebhookReceived": "codestra.moneybee.bank.provider_event_received.v1",
    "PortalConversationOpened": "codestra.moneybee.portal.conversation.opened.v1",
    "PortalNotificationCreated": "codestra.moneybee.portal.notification.created.v1",
    "FinanceLedgerAccountCreated": "codestra.moneybee.finance.ledger_account.created.v1",
    "FinanceAccountingPeriodCreated": "codestra.moneybee.finance.accounting_period.created.v1",
    "FinanceAccountingPeriodClosed": "codestra.moneybee.finance.accounting_period.closed.v1",
    "FinanceJournalPosted": "codestra.moneybee.finance.journal.posted.v1",
}


def canonical_event_type(event_type: str) -> str:
    """Return one Codestra-owned event vocabulary for every MoneyBee event."""

    value = event_type.strip()
    if not value:
        raise ValueError("event_type is required")
    if value.startswith("codestra."):
        return value
    if value in _CANONICAL_ALIASES:
        return _CANONICAL_ALIASES[value]
    if "." in value:
        return f"codestra.moneybee.{value}"
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
    return f"codestra.moneybee.{snake}.v1"


def build_event_envelope(
    *,
    event_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int | None,
    tenant_id: str | None,
    correlation_id: str | None,
    causation_id: str | None,
    occurred_at: str,
    payload: dict[str, Any],
    idempotency_key: str,
    schema_version: int = 1,
    delivery_attempt: int | None = None,
) -> dict[str, Any]:
    """Build the canonical Middleware envelope and strip internal-only metadata.

    ``aggregate_version`` remains a transport input so the publisher signature is
    compatible with outbox records, but it is intentionally not injected into
    ``data``. Domain schemas are closed and must opt in to every data field.
    """

    del aggregate_version
    if not event_id:
        raise ValueError("event_id is required")
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    if not occurred_at:
        raise ValueError("occurred_at is required")

    data = dict(payload)
    actor = data.pop(INTERNAL_ACTOR_KEY, None)
    subject = data.pop(INTERNAL_SUBJECT_KEY, None)
    canonical_type = canonical_event_type(event_type)

    if actor is None:
        actor = {"type": "service", "id": "moneybee-backend"}
    if not isinstance(actor, dict) or actor.get("type") not in {"user", "service", "system"}:
        raise ValueError("event actor is invalid")
    if not str(actor.get("id") or "").strip():
        raise ValueError("event actor id is required")

    subject = str(subject or f"{aggregate_type}:{aggregate_id}")
    effective_tenant = str(tenant_id or PUBLIC_TENANT_SCOPE)
    envelope: dict[str, Any] = {
        "specversion": "1.0",
        "id": str(event_id),
        "type": canonical_type,
        "source": SOURCE_URN,
        "subject": subject,
        "time": occurred_at,
        "tenant_id": effective_tenant,
        "correlation_id": str(correlation_id or event_id),
        "causation_id": str(causation_id or event_id),
        "idempotency_key": str(idempotency_key),
        "schema_version": int(schema_version or 1),
        "actor": {"type": str(actor["type"]), "id": str(actor["id"])},
        "data": data,
    }
    if delivery_attempt is not None:
        envelope["delivery_attempt"] = max(1, int(delivery_attempt))
    return envelope
