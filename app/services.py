import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.auth import Principal
from app.config import settings


APPLICATION_TRANSITIONS: dict[
    models.ApplicationStatus, frozenset[models.ApplicationStatus]
] = {
    models.ApplicationStatus.APPLICATION_STARTED: frozenset(
        {
            models.ApplicationStatus.APPLICATION_IN_PROGRESS,
            models.ApplicationStatus.READY_FOR_MATCHING,
            models.ApplicationStatus.WITHDRAWN,
        }
    ),
    models.ApplicationStatus.APPLICATION_IN_PROGRESS: frozenset(
        {
            models.ApplicationStatus.APPLICATION_COMPLETE,
            models.ApplicationStatus.READY_FOR_MATCHING,
            models.ApplicationStatus.FRAUD_REVIEW,
            models.ApplicationStatus.COMPLIANCE_REVIEW,
            models.ApplicationStatus.WITHDRAWN,
        }
    ),
    models.ApplicationStatus.APPLICATION_COMPLETE: frozenset(
        {
            models.ApplicationStatus.VERIFICATION_PENDING,
            models.ApplicationStatus.READY_FOR_MATCHING,
            models.ApplicationStatus.FRAUD_REVIEW,
            models.ApplicationStatus.COMPLIANCE_REVIEW,
        }
    ),
    models.ApplicationStatus.VERIFICATION_PENDING: frozenset(
        {
            models.ApplicationStatus.READY_FOR_MATCHING,
            models.ApplicationStatus.FRAUD_REVIEW,
            models.ApplicationStatus.COMPLIANCE_REVIEW,
            models.ApplicationStatus.DECLINED,
        }
    ),
    models.ApplicationStatus.FRAUD_REVIEW: frozenset(
        {
            models.ApplicationStatus.READY_FOR_MATCHING,
            models.ApplicationStatus.COMPLIANCE_REVIEW,
            models.ApplicationStatus.DECLINED,
        }
    ),
    models.ApplicationStatus.COMPLIANCE_REVIEW: frozenset(
        {
            models.ApplicationStatus.READY_FOR_MATCHING,
            models.ApplicationStatus.DECLINED,
        }
    ),
    models.ApplicationStatus.READY_FOR_MATCHING: frozenset(
        {
            models.ApplicationStatus.MATCHED,
            models.ApplicationStatus.DECLINED,
            models.ApplicationStatus.FRAUD_REVIEW,
        }
    ),
    models.ApplicationStatus.MATCHED: frozenset(
        {
            models.ApplicationStatus.SUBMITTED_TO_LENDERS,
            models.ApplicationStatus.OFFERS_AVAILABLE,
            models.ApplicationStatus.DECLINED,
        }
    ),
    models.ApplicationStatus.SUBMITTED_TO_LENDERS: frozenset(
        {
            models.ApplicationStatus.UNDERWRITING,
            models.ApplicationStatus.CONDITIONS_PENDING,
            models.ApplicationStatus.OFFERS_AVAILABLE,
            models.ApplicationStatus.DECLINED,
        }
    ),
    models.ApplicationStatus.UNDERWRITING: frozenset(
        {
            models.ApplicationStatus.CONDITIONS_PENDING,
            models.ApplicationStatus.OFFERS_AVAILABLE,
            models.ApplicationStatus.DECLINED,
        }
    ),
    models.ApplicationStatus.CONDITIONS_PENDING: frozenset(
        {
            models.ApplicationStatus.CONDITIONS_COMPLETE,
            models.ApplicationStatus.OFFERS_AVAILABLE,
            models.ApplicationStatus.DECLINED,
        }
    ),
    models.ApplicationStatus.OFFERS_AVAILABLE: frozenset(
        {
            models.ApplicationStatus.OFFER_ACCEPTED,
            models.ApplicationStatus.EXPIRED,
            models.ApplicationStatus.DECLINED,
        }
    ),
    models.ApplicationStatus.OFFER_ACCEPTED: frozenset(
        {
            models.ApplicationStatus.CONDITIONS_PENDING,
            models.ApplicationStatus.CONTRACT_READY,
            models.ApplicationStatus.CANCELLED,
        }
    ),
    models.ApplicationStatus.CONDITIONS_COMPLETE: frozenset(
        {
            models.ApplicationStatus.CONTRACT_READY,
            models.ApplicationStatus.CANCELLED,
        }
    ),
    models.ApplicationStatus.CONTRACT_READY: frozenset(
        {
            models.ApplicationStatus.CONTRACT_SENT,
            models.ApplicationStatus.CANCELLED,
        }
    ),
    models.ApplicationStatus.CONTRACT_SENT: frozenset(
        {
            models.ApplicationStatus.CONTRACT_SIGNED,
            models.ApplicationStatus.EXPIRED,
            models.ApplicationStatus.CANCELLED,
        }
    ),
    models.ApplicationStatus.CONTRACT_SIGNED: frozenset(
        {
            models.ApplicationStatus.APPROVED_FOR_FUNDING,
            models.ApplicationStatus.CANCELLED,
        }
    ),
    models.ApplicationStatus.APPROVED_FOR_FUNDING: frozenset(
        {
            models.ApplicationStatus.FUNDS_SENT,
            models.ApplicationStatus.CANCELLED,
        }
    ),
    models.ApplicationStatus.FUNDS_SENT: frozenset(
        {
            models.ApplicationStatus.FUNDED,
            models.ApplicationStatus.COMPLIANCE_REVIEW,
        }
    ),
    models.ApplicationStatus.FUNDED: frozenset(
        {models.ApplicationStatus.CLOSED}
    ),
}


def payload_digest(payload: schemas.PrequalificationInput) -> str:
    value = payload.model_dump(mode="json", exclude={"anti_bot_token"})
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def _stored_public_prequalification_replay(
    db: AsyncSession,
    *,
    idempotency_key: str,
    request_hash: str,
) -> schemas.LeadAccepted | None:
    row = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == "public",
            models.IdempotencyRecord.route == "/public/prequalifications",
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IDEMPOTENCY_KEY_CONFLICT",
                "message": "The idempotency key was already used with a different prequalification payload.",
            },
        )
    return schemas.LeadAccepted.model_validate(row.response_body)


async def create_lead(
    db: AsyncSession,
    payload: schemas.PrequalificationInput,
    idempotency_key: str,
    request_id: str,
) -> schemas.LeadAccepted:
    if not all(item.accepted for item in payload.consents):
        raise HTTPException(status_code=422, detail="Required consent was not accepted")
    request_hash = payload_digest(payload)
    replay = await _stored_public_prequalification_replay(
        db,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay is not None:
        return replay

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
            payload={"lead_id": str(lead.id), "digest": request_hash},
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
    response = schemas.LeadAccepted(
        lead_id=lead.id,
        reference=f"MB-{str(lead.id).split('-')[0].upper()}",
        next_action={
            "type": "CREATE_ACCOUNT",
            "url": f"http://localhost:5174/start?lead={lead.id}",
        },
        request_id=request_id,
    )
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id="public",
            route="/public/prequalifications",
            request_hash=request_hash,
            response_status=202,
            response_body=response.model_dump(mode="json"),
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _stored_public_prequalification_replay(
            db,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        raise
    return response


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


async def match(
    db: AsyncSession,
    application_id: uuid.UUID,
    principal: Principal,
):
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
    transition_application(
        db,
        application,
        models.ApplicationStatus.MATCHED,
        principal,
        reason="Explainable matching completed",
    )
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
            or_(
                models.ProviderConnection.provider_name == capability.provider,
                models.ProviderConnection.provider_type == capability.provider,
            ),
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
    if broad in principal.permissions and "MONEYBEE" in principal.membership_types:
        return
    if own in principal.permissions and principal.borrower_id is not None:
        if application.borrower_organization_id is not None:
            if application.borrower_organization_id == principal.borrower_id:
                return
        elif application.borrower_subject == principal.subject:
            # Additive-migration compatibility for records awaiting organization backfill.
            return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "RESOURCE_ACCESS_DENIED",
            "message": "The principal cannot access this application.",
        },
    )


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
    allowed = APPLICATION_TRANSITIONS.get(previous, frozenset())
    if to_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_APPLICATION_TRANSITION",
                "from_status": previous.value,
                "to_status": to_status.value,
                "allowed": sorted(value.value for value in allowed),
            },
        )
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


FUNDING_TRANSITIONS: dict[str, frozenset[str]] = {
    "CONDITIONS_PENDING": frozenset(
        {"CONDITIONS_SATISFIED", "DECLINED", "CANCELLED"}
    ),
    "CONDITIONS_SATISFIED": frozenset(
        {"CONTRACT_SIGNED", "DECLINED", "CANCELLED"}
    ),
    "CONTRACT_SIGNED": frozenset(
        {"APPROVED_FOR_FUNDING", "DECLINED", "CANCELLED"}
    ),
    "APPROVED_FOR_FUNDING": frozenset(
        {"FUNDS_SENT", "DECLINED", "CANCELLED"}
    ),
    "FUNDS_SENT": frozenset({"FUNDED", "DECLINED", "CANCELLED"}),
    "FUNDED": frozenset(),
    "DECLINED": frozenset(),
    "CANCELLED": frozenset(),
}


def transition_funding(
    db: AsyncSession,
    funding: models.Funding,
    to_status: str,
    principal: Principal,
    reason: str | None = None,
) -> None:
    previous = funding.status
    if previous == to_status:
        return
    allowed = FUNDING_TRANSITIONS.get(previous, frozenset())
    if to_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_FUNDING_TRANSITION",
                "from_status": previous,
                "to_status": to_status,
                "allowed": sorted(allowed),
            },
        )
    funding.status = to_status
    db.add(
        models.AuditEvent(
            actor_id=principal.subject,
            action=f"FUNDING_{to_status}",
            resource_type="funding",
            resource_id=str(funding.id),
            details={"from_status": previous, "to_status": to_status, "reason": reason},
        )
    )


CONTRACT_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"SENT", "VOIDED"}),
    "SENT": frozenset({"SIGNED", "DECLINED", "EXPIRED", "VOIDED"}),
    "SIGNED": frozenset(),
    "DECLINED": frozenset(),
    "EXPIRED": frozenset(),
    "VOIDED": frozenset(),
}


def transition_contract(
    db: AsyncSession,
    contract: models.Contract,
    to_status: str,
    principal: Principal,
    reason: str | None = None,
) -> None:
    previous = contract.status
    if previous == to_status:
        return
    allowed = CONTRACT_TRANSITIONS.get(previous, frozenset())
    if to_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_CONTRACT_TRANSITION",
                "from_status": previous,
                "to_status": to_status,
                "allowed": sorted(allowed),
            },
        )
    contract.status = to_status
    db.add(
        models.AuditEvent(
            actor_id=principal.subject,
            action=f"CONTRACT_{to_status}",
            resource_type="contract",
            resource_id=str(contract.id),
            details={"from_status": previous, "to_status": to_status, "reason": reason},
        )
    )


async def advance_funding_if_conditions_satisfied(
    db: AsyncSession,
    submission_id: uuid.UUID,
    principal: Principal,
) -> None:
    """Move a funding CONDITIONS_PENDING -> CONDITIONS_SATISFIED once every
    condition on the submission whose offer it came from is SATISFIED or
    WAIVED (or the submission never had any conditions attached). Called
    both right after a condition decision (the natural "did we just finish
    the last one" trigger) and right after offer acceptance (to cover a
    submission with zero conditions, which never triggers a decision).
    """
    submission = await db.get(models.LenderSubmission, submission_id)
    if submission is None:
        return
    funding = await db.scalar(
        select(models.Funding)
        .join(models.Offer, models.Offer.id == models.Funding.offer_id)
        .where(
            models.Funding.application_id == submission.application_id,
            models.Offer.lender_id == submission.lender_id,
            models.Offer.program_id == submission.program_id,
        )
    )
    if funding is None or funding.status != "CONDITIONS_PENDING":
        return
    conditions = (
        await db.scalars(
            select(models.UnderwritingCondition).where(
                models.UnderwritingCondition.submission_id == submission_id
            )
        )
    ).all()
    if all(item.status in {"SATISFIED", "WAIVED"} for item in conditions):
        transition_funding(db, funding, "CONDITIONS_SATISFIED", principal)
        db.add(
            models.Contract(
                application_id=funding.application_id,
                offer_id=funding.offer_id,
                # No real contract-template catalog/versioning exists yet -
                # this is a placeholder until that's a real business
                # decision, not a stand-in for actual legal content.
                template_version="v1",
                status="DRAFT",
            )
        )


# Named, isolated default per docs/codex/CONTRACTS_FUNDING_COMMISSION_RENEWAL_SPEC_DRAFT.md's
# resolved open question 2 - no real eligibility rule confirmed yet, so
# this is a one-line change away from being replaced with the real one.
RENEWAL_ELIGIBILITY_DAYS = 90

# Simpler than the spec draft's original PENDING -> OPPORTUNITY_CREATED ->
# CONTACTED -> ... : a RenewalOpportunity row is only ever created once
# already eligible, so "opportunity created" is redundant with the row's
# own existence. Starts at PENDING (created, not yet contacted).
RENEWAL_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"CONTACTED", "DECLINED", "EXPIRED"}),
    "CONTACTED": frozenset({"CONVERTED", "DECLINED", "EXPIRED"}),
    "CONVERTED": frozenset(),
    "DECLINED": frozenset(),
    "EXPIRED": frozenset(),
}


def transition_renewal_status(
    db: AsyncSession,
    renewal: models.RenewalOpportunity,
    to_status: str,
    principal: Principal,
    reason: str | None = None,
) -> None:
    previous = renewal.status
    if previous == to_status:
        return
    allowed = RENEWAL_STATUS_TRANSITIONS.get(previous, frozenset())
    if to_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_RENEWAL_STATUS_TRANSITION",
                "from_status": previous,
                "to_status": to_status,
                "allowed": sorted(allowed),
            },
        )
    renewal.status = to_status
    db.add(
        models.AuditEvent(
            actor_id=principal.subject,
            action=f"RENEWAL_{to_status}",
            resource_type="renewal_opportunity",
            resource_id=str(renewal.id),
            details={"from_status": previous, "to_status": to_status, "reason": reason},
        )
    )


async def evaluate_renewal_eligibility(db: AsyncSession) -> list[uuid.UUID]:
    """Scans FUNDED fundings old enough to be renewal-eligible and creates
    a RenewalOpportunity for each that doesn't already have one. Meant to
    be called periodically (see app/worker.py) rather than per-request -
    there's no per-funding trigger event the way conditions/contracts have
    one, since eligibility is purely time-based. Returns the ids of newly
    created opportunities."""
    cutoff = datetime.now(UTC) - timedelta(days=RENEWAL_ELIGIBILITY_DAYS)
    fundings = (
        await db.scalars(
            select(models.Funding).where(
                models.Funding.status == "FUNDED",
                models.Funding.funding_confirmed_at.is_not(None),
                models.Funding.funding_confirmed_at <= cutoff,
            )
        )
    ).all()
    created: list[uuid.UUID] = []
    for funding in fundings:
        existing = await db.scalar(
            select(models.RenewalOpportunity).where(
                models.RenewalOpportunity.original_funding_id == funding.id
            )
        )
        if existing is not None:
            continue
        opportunity = models.RenewalOpportunity(
            original_funding_id=funding.id,
            application_id=funding.application_id,
            eligible_from=funding.funding_confirmed_at,
            eligibility_status="ELIGIBLE",
            estimated_amount=funding.funded_amount,
            status="PENDING",
        )
        db.add(opportunity)
        await db.flush()
        created.append(opportunity.id)
    return created
