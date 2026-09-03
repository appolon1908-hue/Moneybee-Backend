from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.integration_models import OperationalException
from app.integrations.base import ESignAdapter, ProviderError
from app.portal.common import problem


_EXCEPTION_CODE = "CONTRACT_VOID_OUTCOME_UNKNOWN"


def _provider_status(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("status") or payload.get("envelopeStatus")
    if value is None:
        return None
    return str(value).strip().lower().removeprefix("envelope-")


def _clear_provider_failure(contract: models.Contract) -> None:
    contract.provider_last_error = None
    contract.provider_next_attempt_at = None
    contract.provider_terminal_at = None
    contract.provider_lease_owner = None
    contract.provider_lease_expires_at = None


async def _exception_for_contract(
    db: AsyncSession,
    contract: models.Contract,
) -> OperationalException | None:
    return await db.scalar(
        select(OperationalException).where(
            OperationalException.fingerprint
            == f"{_EXCEPTION_CODE}:{contract.id}"
        )
    )


async def _record_unknown_outcome(
    db: AsyncSession,
    contract: models.Contract,
    *,
    observed_status: str | None,
) -> None:
    now = models.utcnow()
    contract.provider_last_error = "E-sign void outcome requires provider read-back"
    contract.provider_next_attempt_at = None
    contract.provider_terminal_at = now
    contract.provider_lease_owner = None
    contract.provider_lease_expires_at = None

    exception = await _exception_for_contract(db, contract)
    comment = {
        "at": now.isoformat(),
        "message": "Automatic retry blocked pending provider status reconciliation.",
        "observed_status": observed_status,
    }
    if exception is None:
        db.add(
            OperationalException(
                fingerprint=f"{_EXCEPTION_CODE}:{contract.id}",
                code=_EXCEPTION_CODE,
                severity="HIGH",
                resource_type="contract",
                resource_id=str(contract.id),
                retry_action="READ_BACK_DOCUSIGN_ENVELOPE_STATUS",
                comments=[comment],
            )
        )
    else:
        exception.status = "OPEN"
        exception.resolution = None
        exception.resolved_at = None
        exception.comments = [*list(exception.comments or []), comment]
    await db.commit()


async def _resolve_exception(
    db: AsyncSession,
    contract: models.Contract,
) -> None:
    exception = await _exception_for_contract(db, contract)
    if exception is not None and exception.status == "OPEN":
        exception.status = "RESOLVED"
        exception.resolution = "Provider read-back confirmed the envelope is voided."
        exception.resolved_at = models.utcnow()


def _record_reconciliation_evidence(
    db: AsyncSession,
    contract: models.Contract,
    *,
    attempted_mutations: int,
) -> None:
    db.add(
        models.AuditEvent(
            actor_id="system:contract-void-reconciliation",
            action="CONTRACT_VOID_RECONCILED",
            resource_type="contract",
            resource_id=str(contract.id),
            details={
                "provider": "docusign",
                "provider_reference": contract.external_envelope_id,
                "provider_status": "voided",
                "attempted_mutations": attempted_mutations,
                "confirmation_method": "provider_status_readback",
            },
        )
    )


async def ensure_provider_void_confirmed(
    db: AsyncSession,
    contract: models.Contract,
    *,
    reason: str,
    adapter: ESignAdapter,
) -> None:
    """Confirm a SENT envelope is voided without repeating an unknown mutation.

    On an ambiguous first attempt, a durable operational exception blocks every
    later request from calling `void_envelope` again. Later requests perform only
    provider status read-back and may complete the local transition once the
    provider reports `voided`.
    """
    if contract.status != "SENT" or not contract.external_envelope_id:
        return

    existing_exception = await _exception_for_contract(db, contract)
    if existing_exception is not None and existing_exception.status == "OPEN":
        try:
            status_payload = await adapter.envelope_status(
                envelope_id=contract.external_envelope_id
            )
            observed = _provider_status(status_payload)
        except ProviderError:
            await _record_unknown_outcome(db, contract, observed_status=None)
            problem(
                "CONTRACT_VOID_RECONCILIATION_REQUIRED",
                "The previous e-sign void outcome is still unknown; automatic retry is blocked.",
                503,
            )
        if observed != "voided":
            await _record_unknown_outcome(db, contract, observed_status=observed)
            problem(
                "CONTRACT_VOID_RECONCILIATION_REQUIRED",
                "The previous e-sign void is not confirmed; automatic retry is blocked.",
                409,
            )
        _record_reconciliation_evidence(
            db,
            contract,
            attempted_mutations=contract.provider_attempt_count,
        )
        _clear_provider_failure(contract)
        contract.provider_attempt_count = 0
        await _resolve_exception(db, contract)
        return

    contract.provider_attempt_count += 1
    try:
        response = await adapter.void_envelope(
            envelope_id=contract.external_envelope_id,
            reason=reason,
        )
        observed = _provider_status(response)
        if observed not in {None, "voided"}:
            await _record_unknown_outcome(db, contract, observed_status=observed)
            problem(
                "CONTRACT_VOID_RECONCILIATION_REQUIRED",
                "The e-sign provider did not confirm the void operation.",
                503,
            )
        _clear_provider_failure(contract)
        # A definite synchronous response closes the retry sequence. Ambiguous
        # attempts retain their count through the read-back path below as
        # reconciliation evidence.
        contract.provider_attempt_count = 0
        return
    except ProviderError:
        pass

    try:
        status_payload = await adapter.envelope_status(
            envelope_id=contract.external_envelope_id
        )
        observed = _provider_status(status_payload)
    except ProviderError:
        observed = None

    if observed == "voided":
        _record_reconciliation_evidence(
            db,
            contract,
            attempted_mutations=contract.provider_attempt_count,
        )
        _clear_provider_failure(contract)
        contract.provider_attempt_count = 0
        await _resolve_exception(db, contract)
        return

    await _record_unknown_outcome(db, contract, observed_status=observed)
    problem(
        "CONTRACT_VOID_RECONCILIATION_REQUIRED",
        "The e-sign void outcome is unknown; reconcile the provider operation before retrying.",
        503,
    )
