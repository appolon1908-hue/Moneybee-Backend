import asyncio
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from app.auth import Principal
from app.config import settings
from app.db import SessionLocal
from app.integration_models import IntegrationInboxMessage, OperationalException
from app.integrations.base import ProviderError
from app.integrations.middleware import canonical_event_type
from app.integrations.registry import esign_adapter, malware_scanner, middleware_adapter, storage_adapter
from app.models import Contract, Document, Funding, IntegrationEvent, Owner, OutboxEvent, OutboxStatus
from app.services import (
    effective_capabilities,
    evaluate_renewal_eligibility,
    transition_contract,
    transition_funding,
)


WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

SYSTEM_PRINCIPAL = Principal(
    user_id=uuid.UUID(int=0),
    issuer="system",
    subject="worker:contract-engine",
    organization_ids=(),
    active_organization_id=None,
    roles=frozenset(),
    permissions=frozenset({"*"}),
    membership_types=frozenset(),
    borrower_id=None,
    lender_id=None,
    is_active=True,
)


def external_delivery_enabled() -> bool:
    """Require an explicit runtime gate before leasing or sending any event."""
    return os.getenv("ENABLE_EXTERNAL_DELIVERY", "false").strip().lower() in TRUE_VALUES


async def claim() -> str | None:
    if not external_delivery_enabled():
        return None

    now = datetime.now(UTC)
    async with SessionLocal() as db, db.begin():
        event = await db.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.RETRY]),
                or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
                or_(OutboxEvent.lease_expires_at.is_(None), OutboxEvent.lease_expires_at < now),
            )
            .order_by(OutboxEvent.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not event:
            return None
        event.status = OutboxStatus.LEASED
        event.lease_owner = WORKER_ID
        event.lease_expires_at = now + timedelta(seconds=60)
        event.attempt_count += 1
        event.first_attempt_at = event.first_attempt_at or now
        event.last_attempt_at = now
        event.provider = "codestra"
        event.destination = "codestra:event-ingress"
        return str(event.id)


async def deliver(event_id: str) -> None:
    async with SessionLocal() as db:
        event = await db.get(OutboxEvent, event_id)
        if not event or event.lease_owner != WORKER_ID:
            return
        if not external_delivery_enabled():
            event.status = OutboxStatus.PENDING
            event.lease_owner = None
            event.lease_expires_at = None
            await db.commit()
            return

        try:
            capabilities = await effective_capabilities(db)
            if not capabilities.get("crm.write", False):
                raise ProviderError(
                    "codestra",
                    "crm.write is not enabled and provider-ready",
                )
            adapter = middleware_adapter()
            canonical_type = canonical_event_type(event.event_type)
            result = await adapter.publish(
                event_id=str(event.id),
                event_type=canonical_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=str(event.aggregate_id),
                aggregate_version=event.aggregate_version,
                tenant_id=event.tenant_id,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                occurred_at=event.created_at.isoformat(),
                payload=event.payload,
            )
            db.add(
                IntegrationEvent(
                    provider=result.provider,
                    event_type=canonical_type,
                    aggregate_id=event.aggregate_id,
                    status="DELIVERED",
                    attempts=event.attempt_count,
                    external_id=result.external_id,
                    response=result.response,
                )
            )
            event.status = OutboxStatus.DELIVERED
            event.delivered_at = datetime.now(UTC)
            event.last_error = None
            event.last_error_code = None
        except Exception as exc:
            event.last_error = str(exc)[:1000]
            event.last_error_code = type(exc).__name__[:120]
            event.last_http_status = (
                exc.status_code if isinstance(exc, ProviderError) else None
            )
            db.add(
                IntegrationEvent(
                    provider="codestra",
                    event_type=canonical_event_type(event.event_type),
                    aggregate_id=event.aggregate_id,
                    status="FAILED",
                    attempts=event.attempt_count,
                    last_error=event.last_error,
                )
            )
            terminal = event.attempt_count >= 8
            event.status = OutboxStatus.DEAD if terminal else OutboxStatus.RETRY
            event.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(3600, 2 ** event.attempt_count)
            )
            if terminal:
                fingerprint = f"OUTBOX_RETRY_EXHAUSTED:{event.id}"
                existing = await db.scalar(
                    select(OperationalException).where(
                        OperationalException.fingerprint == fingerprint
                    )
                )
                if existing is None:
                    db.add(
                        OperationalException(
                            fingerprint=fingerprint,
                            code="OUTBOX_RETRY_EXHAUSTED",
                            severity="HIGH",
                            resource_type="outbox_event",
                            resource_id=str(event.id),
                            correlation_id=event.correlation_id,
                            retry_action="REPLAY_OUTBOX_EVENT",
                            comments=[],
                        )
                    )
        finally:
            event.lease_owner = None
            event.lease_expires_at = None
            await db.commit()


def esign_live_send_enabled() -> bool:
    """Named after the ESIGN_LIVE_SEND capability-freeze flag already
    referenced in docs/codex/MB_RELEASE_READINESS_PACKET_20260827.md -
    fail-closed like external_delivery_enabled() above."""
    return os.getenv("ESIGN_LIVE_SEND", "false").strip().lower() in TRUE_VALUES


async def send_pending_contract_envelope() -> str | None:
    """Claims and sends at most one DRAFT contract per call. Not wired
    into run()'s loop - deployment decides how this gets scheduled,
    independent of the CRM outbox delivery loop above so the two
    concerns' retry/failure semantics don't get entangled. Returns the
    contract id processed, or None if there was nothing to do."""
    if not esign_live_send_enabled():
        return None
    async with SessionLocal() as db, db.begin():
        contract = await db.scalar(
            select(Contract)
            .where(Contract.status == "DRAFT")
            .order_by(Contract.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if contract is None:
            return None
        signer = await db.scalar(
            select(Owner)
            .where(Owner.application_id == contract.application_id)
            .order_by(Owner.ownership_percent.desc(), Owner.created_at)
            .limit(1)
        )
        if signer is None or not signer.email:
            transition_contract(
                db,
                contract,
                "VOIDED",
                SYSTEM_PRINCIPAL,
                reason="No owner with an email address to sign as",
            )
            return str(contract.id)
        try:
            result = await esign_adapter().send_envelope(
                contract_id=str(contract.id),
                signer_email=signer.email,
                signer_name=f"{signer.first_name} {signer.last_name}",
            )
        except ProviderError:
            # Left as DRAFT - the next call to this function retries it.
            # No dead-letter/backoff bookkeeping yet, unlike the CRM outbox
            # above; add if send failures turn out to need it in practice.
            return str(contract.id)
        contract.provider = "docusign"
        contract.external_envelope_id = str(
            result.get("envelopeId") or result.get("envelope_id") or ""
        ) or None
        transition_contract(db, contract, "SENT", SYSTEM_PRINCIPAL)
        return str(contract.id)


async def scan_pending_document() -> str | None:
    """Claims and scans at most one QUARANTINED document per call - the
    step app/portal/borrower.py's upload flow writes a DocumentUploaded
    outbox event for (destination="document-scanner") but that nothing
    ever consumed, leaving every uploaded document permanently
    QUARANTINED. Fails closed: if malware scanning isn't configured,
    documents simply stay QUARANTINED rather than being waved through -
    matches the intent already encoded in the default status and in
    app/readiness.py's "not certified" note. Returns the document id
    processed, or None if there was nothing to do."""
    if settings.malware_scan_provider == "disabled":
        return None
    async with SessionLocal() as db, db.begin():
        document = await db.scalar(
            select(Document)
            .where(Document.status == "QUARANTINED")
            .order_by(Document.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if document is None:
            return None
        try:
            content = await storage_adapter().get_private(object_key=document.storage_key)
            result = await malware_scanner().scan(content)
        except ProviderError:
            # Left as QUARANTINED - the next call retries it. A storage or
            # scanner outage must never move a document to CLEAN.
            return str(document.id)
        document.scan_provider = result.provider
        document.scan_result = result.raw
        document.scanned_at = datetime.now(UTC)
        if result.clean:
            document.status = "CLEAN"
        else:
            document.status = "REJECTED"
            try:
                await storage_adapter().delete_private(object_key=document.storage_key)
            except ProviderError:
                pass
        return str(document.id)


def _docusign_envelope_id(payload: dict) -> str | None:
    """DocuSign Connect webhook payload shape varies by configuration
    (legacy XML-derived JSON vs. the newer eventNotification format) and
    this integration has never been configured against a real DocuSign
    account, so this checks the field names DocuSign's own docs use for
    each - verify against the actual configured webhook format before
    this goes live."""
    return (
        payload.get("envelopeId")
        or payload.get("envelope_id")
        or payload.get("data", {}).get("envelopeId")
    )


def _docusign_envelope_status(payload: dict) -> str | None:
    status = (
        payload.get("status")
        or payload.get("event")
        or payload.get("data", {}).get("envelopeSummary", {}).get("status")
    )
    return str(status).lower() if status else None


DOCUSIGN_STATUS_TO_CONTRACT_STATUS = {
    "completed": "SIGNED",
    "declined": "DECLINED",
    "voided": "VOIDED",
}


async def process_pending_docusign_event() -> str | None:
    """Claims and applies at most one received DocuSign inbox message per
    call. Same scheduling note as send_pending_contract_envelope()."""
    async with SessionLocal() as db, db.begin():
        message = await db.scalar(
            select(IntegrationInboxMessage)
            .where(
                IntegrationInboxMessage.provider == "docusign",
                IntegrationInboxMessage.status == "RECEIVED",
            )
            .order_by(IntegrationInboxMessage.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if message is None:
            return None

        envelope_id = _docusign_envelope_id(message.payload)
        new_status = DOCUSIGN_STATUS_TO_CONTRACT_STATUS.get(
            _docusign_envelope_status(message.payload) or ""
        )
        message.attempts += 1
        message.processed_at = datetime.now(UTC)
        if not envelope_id or not new_status:
            message.status = "IGNORED"
            message.last_error = "Unrecognized envelope id or status in payload"
            return str(message.id)

        contract = await db.scalar(
            select(Contract).where(Contract.external_envelope_id == envelope_id)
        )
        if contract is None:
            message.status = "FAILED"
            message.last_error = f"No contract found for envelope {envelope_id}"
            return str(message.id)

        try:
            transition_contract(db, contract, new_status, SYSTEM_PRINCIPAL)
        except Exception as exc:
            message.status = "FAILED"
            message.last_error = str(exc)[:1000]
            return str(message.id)

        if new_status == "SIGNED":
            contract.signed_at = datetime.now(UTC)
            funding = await db.scalar(
                select(Funding).where(
                    Funding.application_id == contract.application_id,
                    Funding.offer_id == contract.offer_id,
                )
            )
            if funding is not None and funding.status == "CONDITIONS_SATISFIED":
                transition_funding(db, funding, "CONTRACT_SIGNED", SYSTEM_PRINCIPAL)

        message.status = "PROCESSED"
        return str(message.id)


async def evaluate_pending_renewals() -> list[str]:
    """Scans for newly-eligible renewal opportunities in one pass. Unlike
    the contract/CRM steps above, there's no per-event trigger to hang
    this off - eligibility is purely time-based (funding_confirmed_at vs.
    RENEWAL_ELIGIBILITY_DAYS) - so this is meant to run periodically
    rather than be claimed one row at a time. No capability-freeze flag:
    creating a RenewalOpportunity row is purely internal bookkeeping, not
    an external call, unlike sending a contract envelope or CRM event."""
    async with SessionLocal() as db, db.begin():
        created = await evaluate_renewal_eligibility(db)
        return [str(item) for item in created]


async def run() -> None:
    renewal_tick = 0
    while True:
        did_work = False
        if external_delivery_enabled():
            event_id = await claim()
            if event_id:
                await deliver(event_id)
                did_work = True
        if esign_live_send_enabled():
            did_work = bool(await send_pending_contract_envelope()) or did_work
        did_work = bool(await process_pending_docusign_event()) or did_work
        did_work = bool(await scan_pending_document()) or did_work
        renewal_tick += 1
        if renewal_tick >= 30:
            did_work = bool(await evaluate_pending_renewals()) or did_work
            renewal_tick = 0
        if not did_work:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(run())
