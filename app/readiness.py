from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, services
from app.config import settings
from app.integration_models import IntegrationInboxMessage, OperationalException
from app.integrations.registry import provider_statuses


CAPABILITY_BY_PROVIDER_TYPE = {
    "middleware": "crm.write",
    "crm": "crm.write",
    "bank": "bank.live_connection",
    "kyb": "kyb.live_verification",
    "credit": "credit.live_pull",
    "lender": "lenders.live_submission",
    "esign": "esign.live_send",
    "email": "communications.live_email",
    "sms": "communications.live_sms",
}


async def system_readiness(db: AsyncSession) -> dict:
    capabilities = await services.effective_capabilities(db)
    adapter_status: dict[str, str] = {}
    blockers: list[str] = []

    for row in provider_statuses():
        capability = CAPABILITY_BY_PROVIDER_TYPE.get(row.provider_type)
        ready = bool(capability and capabilities.get(capability, False))
        if row.selected and row.configured and ready:
            status = "READY"
        elif row.selected and row.configured:
            status = "CONFIGURED_NOT_ENABLED"
        elif row.selected:
            status = "INCOMPLETE"
            blockers.append(f"{row.provider} configuration is incomplete")
        else:
            status = "DISABLED"
        adapter_status[row.provider] = status

    dead_outbox = (
        await db.scalar(
            select(func.count(models.OutboxEvent.id)).where(
                models.OutboxEvent.status == models.OutboxStatus.DEAD
            )
        )
        or 0
    )
    pending_outbox = (
        await db.scalar(
            select(func.count(models.OutboxEvent.id)).where(
                models.OutboxEvent.status.in_(
                    [models.OutboxStatus.PENDING, models.OutboxStatus.RETRY]
                )
            )
        )
        or 0
    )
    failed_inbox = (
        await db.scalar(
            select(func.count(IntegrationInboxMessage.id)).where(
                IntegrationInboxMessage.status.in_(["FAILED", "DEAD"])
            )
        )
        or 0
    )
    pending_inbox = (
        await db.scalar(
            select(func.count(IntegrationInboxMessage.id)).where(
                IntegrationInboxMessage.status.in_(["RECEIVED", "RETRY"])
            )
        )
        or 0
    )
    open_exceptions = (
        await db.scalar(
            select(func.count(OperationalException.id)).where(
                OperationalException.status == "OPEN"
            )
        )
        or 0
    )

    if dead_outbox:
        blockers.append(f"{dead_outbox} outbox event(s) are terminal")
    if failed_inbox:
        blockers.append(f"{failed_inbox} inbox message(s) failed")
    if open_exceptions:
        blockers.append(f"{open_exceptions} operational exception(s) are open")

    release_evidence = {
        "SOURCE_SHA": settings.source_sha,
        "API_IMAGE_DIGEST": settings.api_image_digest,
        "FRONTEND_IMAGE_DIGEST": settings.frontend_image_digest,
        "MIGRATION_HEAD": settings.migration_head,
        "CONFIGURATION_CHECKSUM": settings.configuration_checksum,
        "SBOM_DIGEST": settings.sbom_digest,
        "PROVENANCE_DIGEST": settings.provenance_digest,
        "BACKUP_REFERENCE": settings.backup_reference,
    }
    for key, value in release_evidence.items():
        if not value:
            blockers.append(f"{key} evidence is missing")

    for key, value in (
        ("BACKUP_STATUS", settings.backup_status),
        ("PITR_STATUS", settings.pitr_status),
        ("OFFHOST_BACKUP_STATUS", settings.offhost_backup_status),
        ("RESTORE_STATUS", settings.restore_status),
        ("REDIS_RECOVERY_STATUS", settings.redis_recovery_status),
        ("APPLICATION_RESTORE_STATUS", settings.application_restore_status),
        ("STAGING_STATUS", settings.staging_status),
    ):
        if value != "PASS":
            blockers.append(f"{key} is {value}")

    architecture_evidence = {
        "AUTHORIZATION_STATUS": settings.authorization_status,
        "COMMAND_STATUS": settings.command_status,
        "CONCURRENCY_STATUS": settings.concurrency_status,
        "DOCUMENT_SECURITY_STATUS": settings.document_security_status,
        "PII_SECURITY_STATUS": settings.pii_security_status,
        "OBSERVABILITY_STATUS": settings.observability_status,
        "IDEMPOTENCY_STATUS": settings.idempotency_status,
    }
    for key, value in architecture_evidence.items():
        if value != "PASS":
            blockers.append(f"{key} is {value}")

    auth_status = (
        "PASS"
        if settings.oidc_issuer == "https://auth.codestra.co/realms/codestra"
        and not (settings.app_env == "production" and settings.local_auth_bypass)
        else "FAIL"
    )
    if auth_status != "PASS":
        blockers.append("Canonical production authentication is not enforced")

    final_status = (
        "READY"
        if settings.app_env == "production" and auth_status == "PASS" and not blockers
        else ("BLOCKED" if auth_status == "FAIL" else "PARTIAL")
    )
    enabled_features = sorted(key for key, enabled in capabilities.items() if enabled)

    return {
        "FINAL_STATUS": final_status,
        "OVERALL_SYSTEM_STATUS": final_status,
        "ENVIRONMENT": settings.app_env,
        **release_evidence,
        "AUTH_STATUS": auth_status,
        **architecture_evidence,
        "OUTBOX_STATUS": "FAIL" if dead_outbox else "PASS",
        "INBOX_STATUS": "FAIL" if failed_inbox else "PASS",
        "OUTBOX_PENDING": pending_outbox,
        "INBOX_PENDING": pending_inbox,
        "OPEN_OPERATIONAL_EXCEPTIONS": open_exceptions,
        "ADAPTER_STATUS": adapter_status,
        "BACKUP_STATUS": settings.backup_status,
        "PITR_STATUS": settings.pitr_status,
        "OFFHOST_BACKUP_STATUS": settings.offhost_backup_status,
        "RESTORE_STATUS": settings.restore_status,
        "REDIS_RECOVERY_STATUS": settings.redis_recovery_status,
        "APPLICATION_RESTORE_STATUS": settings.application_restore_status,
        "STAGING_STATUS": settings.staging_status,
        "PRODUCTION_FEATURES_ENABLED": enabled_features,
        "BLOCKERS": blockers,
        "NEXT_SAFE_ACTION": blockers[0] if blockers else "Continue Step 1 verification",
    }
