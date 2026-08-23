import hashlib
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.auth import Principal
from app.config import settings


def payload_digest(payload: schemas.PrequalificationInput) -> str:
    value = payload.model_dump(mode="json", exclude={"anti_bot_token"})
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def create_lead(
    db: AsyncSession,
    payload: schemas.PrequalificationInput,
    idempotency_key: str,
    request_id: str,
) -> schemas.LeadAccepted:
    if not all(item.accepted for item in payload.consents):
        raise HTTPException(status_code=422, detail="Required consent was not accepted")
    lead = models.Lead(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        email=str(payload.email).lower(),
        phone=payload.phone,
        business_name=payload.business_name.strip(),
        funding_amount=payload.funding_amount,
        monthly_revenue=payload.monthly_revenue,
        use_of_funds=payload.use_of_funds,
        time_in_business_months=payload.time_in_business_months,
        postal_code=payload.postal_code.strip(),
        attribution=payload.marketing.model_dump(mode="json"),
    )
    db.add(lead)
    await db.flush()
    for item in payload.consents:
        db.add(
            models.Consent(
                lead_id=lead.id,
                consent_type=item.type,
                document_version=item.document_version,
                evidence={"accepted": True, "request_id": request_id},
            )
        )
    db.add(
        models.OutboxEvent(
            event_type="LeadSubmitted",
            aggregate_id=lead.id,
            payload={"lead_id": str(lead.id), "digest": payload_digest(payload)},
            idempotency_key=idempotency_key,
        )
    )
    db.add(
        models.AuditEvent(
            actor_id="public",
            action="LEAD_RECEIVED",
            resource_type="lead",
            resource_id=str(lead.id),
            request_id=request_id,
            details={"landing_page": payload.marketing.landing_page},
        )
    )
    await db.commit()
    return schemas.LeadAccepted(
        lead_id=lead.id,
        reference=f"MB-{str(lead.id).split('-')[0].upper()}",
        next_action={
            "type": "CREATE_ACCOUNT",
            "url": f"http://localhost:5174/start?lead={lead.id}",
        },
        request_id=request_id,
    )


def score(application: models.Application, program: models.LenderProgram):
    reasons: list[str] = []
    if application.requested_amount < program.min_amount:
        reasons.append("REQUEST_BELOW_MINIMUM")
    if application.requested_amount > program.max_amount:
        reasons.append("REQUEST_ABOVE_MAXIMUM")
    if application.monthly_revenue < program.minimum_monthly_revenue:
        reasons.append("REVENUE_BELOW_MINIMUM")
    if application.time_in_business_months < program.minimum_time_in_business_months:
        reasons.append("TIME_IN_BUSINESS_BELOW_MINIMUM")
    if application.state and program.states and application.state not in program.states:
        reasons.append("STATE_NOT_SUPPORTED")
    if application.industry and application.industry in program.excluded_industries:
        reasons.append("INDUSTRY_EXCLUDED")
    return not reasons, max(0, 100 - len(reasons) * 20), reasons


async def match(db: AsyncSession, application_id: uuid.UUID):
    application = await db.get(models.Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    programs = list((await db.scalars(select(models.LenderProgram).where(models.LenderProgram.active))).all())
    await db.execute(
        delete(models.ApplicationMatch).where(
            models.ApplicationMatch.application_id == application.id
        )
    )
    results = []
    for program in programs:
        eligible, value, reasons = score(application, program)
        item = models.ApplicationMatch(
            application_id=application.id,
            lender_id=program.lender_id,
            program_id=program.id,
            eligible=eligible,
            score=value,
            reasons=reasons,
            program_version=program.version,
        )
        db.add(item)
        results.append(item)
    application.status = models.ApplicationStatus.MATCHED
    await db.commit()
    for item in results:
        await db.refresh(item)
    return results


async def capability_is_ready(db: AsyncSession, capability: models.CapabilityFlag) -> bool:
    if not capability.enabled:
        return False
    if not capability.provider:
        return True
    provider = await db.scalar(
        select(models.ProviderConnection).where(
            models.ProviderConnection.provider_name == capability.provider,
            models.ProviderConnection.environment == settings.app_env,
            models.ProviderConnection.status == models.ProviderStatus.READY,
        )
    )
    return provider is not None


async def effective_capabilities(db: AsyncSession) -> dict[str, bool]:
    capabilities = (
        await db.scalars(
            select(models.CapabilityFlag)
            .where(models.CapabilityFlag.environment == settings.app_env)
            .order_by(models.CapabilityFlag.key)
        )
    ).all()
    return {
        capability.key: await capability_is_ready(db, capability)
        for capability in capabilities
    }


async def require_capability(db: AsyncSession, key: str) -> models.CapabilityFlag:
    capability = await db.scalar(
        select(models.CapabilityFlag).where(
            models.CapabilityFlag.key == key,
            models.CapabilityFlag.environment == settings.app_env,
        )
    )
    if capability is None or not await capability_is_ready(db, capability):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CAPABILITY_UNAVAILABLE",
                "capability": key,
                "message": "This capability is not enabled and provider-ready.",
            },
        )
    return capability


def authorize_application(
    application: models.Application,
    principal: Principal,
    *,
    write: bool = False,
) -> None:
    if "*" in principal.permissions:
        return
    broad = "application.edit" if write else "application.read"
    own = "application.edit.own" if write else "application.read.own"
    if broad in principal.permissions:
        return
    if own in principal.permissions and application.borrower_subject == principal.subject:
        return
    raise HTTPException(status_code=403, detail="Application access denied")


async def get_authorized_application(
    db: AsyncSession,
    application_id: uuid.UUID,
    principal: Principal,
    *,
    write: bool = False,
) -> models.Application:
    application = await db.get(models.Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    authorize_application(application, principal, write=write)
    return application


async def application_requirements(
    db: AsyncSession,
    application: models.Application,
) -> dict:
    business = await db.scalar(
        select(models.Business).where(models.Business.application_id == application.id)
    )
    financial = await db.scalar(
        select(models.FinancialProfile).where(
            models.FinancialProfile.application_id == application.id
        )
    )
    owners = await db.scalar(
        select(func.count(models.Owner.id)).where(
            models.Owner.application_id == application.id
        )
    )
    consents = await db.scalar(
        select(func.count(models.Consent.id)).where(
            or_(
                models.Consent.application_id == application.id,
                models.Consent.lead_id == application.lead_id,
            )
        )
    )
    values = [
        {
            "code": "BUSINESS_INFORMATION",
            "label": "Business information",
            "complete": business is not None,
        },
        {
            "code": "FINANCIAL_PROFILE",
            "label": "Financial profile",
            "complete": financial is not None,
        },
        {
            "code": "OWNERS",
            "label": "Ownership information",
            "complete": bool(owners),
        },
        {
            "code": "CONSENTS",
            "label": "Required consents",
            "complete": bool(consents),
        },
    ]
    for value in values:
        value["status"] = "COMPLETE" if value["complete"] else "ACTION_REQUIRED"
    completed = sum(1 for value in values if value["complete"])
    next_item = next((value for value in values if not value["complete"]), None)
    return {
        "completion_percentage": int(completed / len(values) * 100),
        "ready_to_submit": completed == len(values),
        "next_action": next_item,
        "requirements": values,
    }


def transition_application(
    db: AsyncSession,
    application: models.Application,
    to_status: models.ApplicationStatus,
    principal: Principal,
    reason: str | None = None,
) -> None:
    previous = application.status
    if previous == to_status:
        return
    application.status = to_status
    application.version += 1
    db.add(
        models.ApplicationStatusHistory(
            application_id=application.id,
            from_status=previous.value if hasattr(previous, "value") else str(previous),
            to_status=to_status.value,
            reason=reason,
            changed_by=principal.subject,
        )
    )
