import asyncio
import hashlib
import os
import secrets
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
from app.models import (
    Application,
    ApplicationStatus,
    Contract,
    Document,
    Funding,
    IntegrationEvent,
    Owner,
    OutboxEvent,
    OutboxStatus,
)
from app.services import (
    effective_capabilities,
    evaluate_renewal_eligibility,
    transition_application,
    transition_contract,
    transition_funding,
)


WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
PROVIDER_MAX_ATTEMPTS = 8
PROVIDER_LEASE_SECONDS = 120

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


def provider_retry_delay_seconds(item_id: uuid.UUID, attempt_count: int) -> int:
    """Exponential backoff with deterministic bounded jitter (0-25%)."""
    base = min(3600, 2 ** max(1, attempt_count))
    digest = hashlib.sha256(f"{item_id}:{attempt_count}".encode()).digest()
    jitter_limit = base // 4
    jitter = int.from_bytes(digest[:2], "big") % (jitter_limit + 1)
    return min(3600, base + jitter)


def _lease_provider_item(item: Contract | Document, now: datetime) -> None:
    item.provider_lease_owner = WORKER_ID
    item.provider_lease_expires_at = now + timedelta(seconds=PROVIDER_LEASE_SECONDS)
    item.provider_attempt_count += 1


def _provider_failed(item: Contract | Document, exc: ProviderError, now: datetime) -> None:
    item.provider_last_error = str(exc)[:1000]
    item.provider_lease_owner = None
    item.provider_lease_expires_at = None
    if item.provider_attempt_count >= PROVIDER_MAX_ATTEMPTS:
        item.provider_terminal_at = now
        item.provider_next_attempt_at = None
    else:
        item.provider_next_attempt_at = now + timedelta(
            seconds=provider_retry_delay_seconds(item.id, item.provider_attempt_count)
        )


def _provider_succeeded(item: Contract | Document) -> None:
    item.provider_last_error = None
    item.provider_next_attempt_at = None
    item.provider_lease_owner = None
    item.provider_lease_expires_at = None


async def send_pending_contract_envelope() -> str | None:
    """Claims and sends at most one DRAFT contract per call. Not wired
    into run()'s loop - deployment decides how this gets scheduled,
    independent of the CRM outbox delivery loop above so the two
    concerns' retry/failure semantics don't get entangled. Returns the
    contract id processed, or None if there was nothing to do."""
    if not esign_live_send_enabled():
        return None
    now = datetime.now(UTC)
    async with SessionLocal() as db, db.begin():
        contract = await db.scalar(
            select(Contract)
            .where(
                Contract.status == "DRAFT",
                Contract.provider_terminal_at.is_(None),
                or_(
                    Contract.provider_next_attempt_at.is_(None),
                    Contract.provider_next_attempt_at <= now,
                ),
                or_(
                    Contract.provider_lease_expires_at.is_(None),
                    Contract.provider_lease_expires_at < now,
                ),
            )
            .order_by(Contract.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if contract is None:
            return None
        _lease_provider_item(contract, now)
        application = await db.scalar(
            select(Application)
            .where(Application.id == contract.application_id)
            .with_for_update()
        )
        if application is None:
            _provider_failed(
                contract,
                ProviderError("moneybee", "contract application is missing"),
                datetime.now(UTC),
            )
            return None
        if application.status in {
            ApplicationStatus.DECLINED,
            ApplicationStatus.CANCELLED,
            ApplicationStatus.EXPIRED,
            ApplicationStatus.WITHDRAWN,
        }:
            transition_contract(
                db,
                contract,
                "VOIDED",
                SYSTEM_PRINCIPAL,
                reason=f"Application is terminal: {application.status.value}",
            )
            _provider_succeeded(contract)
            return str(contract.id)
        if application.status not in {
            ApplicationStatus.CONDITIONS_COMPLETE,
            ApplicationStatus.CONTRACT_READY,
        }:
            _provider_failed(
                contract,
                ProviderError(
                    "moneybee",
                    f"application is not ready for contract delivery: "
                    f"{application.status.value}",
                ),
                datetime.now(UTC),
            )
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
        except ProviderError as exc:
            _provider_failed(contract, exc, datetime.now(UTC))
            if contract.provider_terminal_at is not None:
                db.add(
                    OperationalException(
                        fingerprint=f"CONTRACT_PROVIDER_RETRY_EXHAUSTED:{contract.id}",
                        code="CONTRACT_PROVIDER_RETRY_EXHAUSTED",
                        severity="HIGH",
                        resource_type="contract",
                        resource_id=str(contract.id),
                        retry_action="REVIEW_CONTRACT_PROVIDER_FAILURE",
                        comments=[],
                    )
                )
            return None
        raw_envelope_id = result.get("envelopeId") or result.get("envelope_id")
        envelope_id = (
            str(raw_envelope_id).strip() if raw_envelope_id is not None else ""
        )
        if not envelope_id:
            _provider_failed(
                contract,
                ProviderError("docusign", "provider response omitted envelope identifier"),
                datetime.now(UTC),
            )
            return None
        contract.provider = "docusign"
        contract.external_envelope_id = envelope_id
        transition_contract(db, contract, "SENT", SYSTEM_PRINCIPAL)
        if application.status == ApplicationStatus.CONDITIONS_COMPLETE:
            transition_application(
                db,
                application,
                ApplicationStatus.CONTRACT_READY,
                SYSTEM_PRINCIPAL,
                reason="E-sign envelope prepared for delivery",
            )
        transition_application(
            db,
            application,
            ApplicationStatus.CONTRACT_SENT,
            SYSTEM_PRINCIPAL,
            reason="E-sign envelope sent",
        )
        _provider_succeeded(contract)
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
    now = datetime.now(UTC)
    async with SessionLocal() as db, db.begin():
        document = await db.scalar(
            select(Document)
            .where(
                Document.status == "QUARANTINED",
                Document.provider_terminal_at.is_(None),
                or_(
                    Document.provider_next_attempt_at.is_(None),
                    Document.provider_next_attempt_at <= now,
                ),
                or_(
                    Document.provider_lease_expires_at.is_(None),
                    Document.provider_lease_expires_at < now,
                ),
            )
            .order_by(Document.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if document is None:
            return None
        _lease_provider_item(document, now)
        try:
            version_id = (document.storage_version_id or "").strip()
            if not version_id or version_id.lower() == "null":
                document.status = "REUPLOAD_REQUIRED"
                document.scan_provider = "storage-versioning"
                document.scan_result = "IMMUTABLE_STORAGE_VERSION_REQUIRED"
                document.provider_last_error = "immutable stored-object version is missing"
                document.provider_next_attempt_at = None
                document.provider_terminal_at = None
                document.provider_lease_owner = None
                document.provider_lease_expires_at = None
                db.add(
                    OperationalException(
                        fingerprint=f"DOCUMENT_REUPLOAD_REQUIRED:{document.id}",
                        code="DOCUMENT_REUPLOAD_REQUIRED",
                        severity="HIGH",
                        resource_type="document",
                        resource_id=str(document.id),
                        retry_action="CREATE_NEW_VERSIONED_UPLOAD_SESSION",
                        comments=[],
                    )
                )
                return str(document.id)
            content = await storage_adapter().get_private(
                object_key=document.storage_key,
                version_id=version_id,
            )
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if not secrets.compare_digest(actual_sha256, document.sha256.lower()):
                document.status = "REJECTED"
                document.scan_provider = "integrity-check"
                document.scan_result = "STORED_DOCUMENT_CHECKSUM_MISMATCH"
                document.scanned_at = datetime.now(UTC)
                document.provider_last_error = "stored document checksum mismatch"
                document.provider_terminal_at = datetime.now(UTC)
                document.provider_next_attempt_at = None
                document.provider_lease_owner = None
                document.provider_lease_expires_at = None
                db.add(
                    OperationalException(
                        fingerprint=f"DOCUMENT_CHECKSUM_MISMATCH:{document.id}",
                        code="DOCUMENT_CHECKSUM_MISMATCH",
                        severity="HIGH",
                        resource_type="document",
                        resource_id=str(document.id),
                        retry_action="REUPLOAD_AND_REVIEW_DOCUMENT_INTEGRITY",
                        comments=[],
                    )
                )
                return str(document.id)
            result = await malware_scanner().scan(content)
        except ProviderError as exc:
            # Remains quarantined, but is not immediately eligible again.
            _provider_failed(document, exc, datetime.now(UTC))
            if document.provider_terminal_at is not None:
                db.add(
                    OperationalException(
                        fingerprint=f"DOCUMENT_SCAN_RETRY_EXHAUSTED:{document.id}",
                        code="DOCUMENT_SCAN_RETRY_EXHAUSTED",
                        severity="HIGH",
                        resource_type="document",
                        resource_id=str(document.id),
                        retry_action="REVIEW_DOCUMENT_SCAN_FAILURE",
                        comments=[],
                    )
                )
            return None
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
        _provider_succeeded(document)
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
        or payload.get("data", {}).get("envelopeSummary", {}).get("status")
        or payload.get("event")
    )
    if not status:
        return None
    normalized = str(status).lower()
    return normalized.removeprefix("envelope-")


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
                or_(IntegrationInboxMessage.next_attempt_at.is_(None), IntegrationInboxMessage.next_attempt_at <= datetime.now(UTC)),
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
            select(Contract).where(Contract.external_envelope_id == envelope_id).with_for_update()
        )
        if contract is None:
            if message.attempts >= 8:
                message.status = "FAILED"
                message.next_attempt_at = None
            else:
                message.status = "RECEIVED"
                message.next_attempt_at = datetime.now(UTC) + timedelta(
                    seconds=provider_retry_delay_seconds(message.id, message.attempts)
                )
                message.processed_at = None
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
                ).with_for_update()
            )
            if funding is not None and funding.status == "CONDITIONS_SATISFIED":
                await transition_funding(db, funding, "CONTRACT_SIGNED", SYSTEM_PRINCIPAL)

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
