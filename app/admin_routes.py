import hashlib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import compliance_models, compliance_service, domain_logic, models, schemas, services
from app.auth import Principal, current_principal, require_permission
from app.contract_void_service import ensure_provider_void_confirmed
from app.db import get_db
from app.idempotency import acquire_idempotency_lock
from app.integrations.registry import esign_adapter, provider_statuses


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


@router.get("/admin/dashboard", tags=["admin"])
async def dashboard(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    return {
        "leads": await db.scalar(select(func.count()).select_from(models.Lead)) or 0,
        "applications": await db.scalar(select(func.count()).select_from(models.Application)) or 0,
        "offers": await db.scalar(select(func.count()).select_from(models.Offer)) or 0,
        "funded": await db.scalar(
            select(func.count())
            .select_from(models.Application)
            .where(models.Application.status == models.ApplicationStatus.FUNDED)
        )
        or 0,
        "data_status": "live",
    }


@router.get("/admin/crm/events", tags=["admin"])
async def crm_events(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    events = (
        await db.scalars(select(models.OutboxEvent).order_by(models.OutboxEvent.created_at.desc()))
    ).all()
    return [
        {
            "id": str(event.id),
            "event_type": event.event_type,
            "status": event.status,
            "attempt_count": event.attempt_count,
            "last_error": event.last_error,
        }
        for event in events
    ]


@router.get("/admin/capabilities", tags=["admin"])
async def capabilities(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.read"))],
):
    items = (
        await db.scalars(
            select(models.CapabilityFlag).order_by(
                models.CapabilityFlag.environment, models.CapabilityFlag.key
            )
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "key": item.key,
            "environment": item.environment,
            "enabled": item.enabled,
            "provider": item.provider,
            "provider_ready": await services.capability_is_ready(db, item),
            "reason": item.reason,
            "enabled_at": item.enabled_at,
            "enabled_by": item.enabled_by,
        }
        for item in items
    ]


@router.get("/admin/provider-connections", tags=["admin"])
async def provider_connections(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.read"))],
):
    items = (
        await db.scalars(
            select(models.ProviderConnection).order_by(
                models.ProviderConnection.environment,
                models.ProviderConnection.provider_type,
                models.ProviderConnection.provider_name,
            )
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "provider_type": item.provider_type,
            "provider_name": item.provider_name,
            "environment": item.environment,
            "status": item.status,
            "last_health_check": item.last_health_check,
            "last_success": item.last_success,
            "last_failure": item.last_failure,
        }
        for item in items
    ]


@router.get(
    "/admin/fundings",
    response_model=list[schemas.FundingRead],
    tags=["admin", "funding"],
)
async def admin_fundings(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    return list(
        (await db.scalars(select(models.Funding).order_by(models.Funding.created_at.desc()))).all()
    )


async def _load_funding_or_404(
    db: AsyncSession,
    funding_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> models.Funding:
    query = select(models.Funding).where(models.Funding.id == funding_id)
    if for_update:
        query = query.with_for_update()
    funding = await db.scalar(query)
    if funding is None:
        raise HTTPException(status_code=404, detail="Funding not found")
    return funding


async def _load_contract_or_404(
    db: AsyncSession, contract_id: uuid.UUID, *, for_update: bool = False
) -> models.Contract:
    query = select(models.Contract).where(models.Contract.id == contract_id)
    if for_update:
        query = query.with_for_update()
    contract = await db.scalar(query)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


async def _funding_idempotency_replay(
    db: AsyncSession,
    *,
    route: str,
    actor_id: str,
    idempotency_key: str,
    request_hash: str,
) -> models.IdempotencyRecord | None:
    replay = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == actor_id,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if replay and replay.request_hash != request_hash:
        raise HTTPException(status_code=409, detail="Idempotency key payload conflict")
    return replay


def _request_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@router.post(
    "/admin/fundings/{funding_id}/approve",
    response_model=schemas.FundingRead,
    tags=["admin", "funding"],
)
async def approve_funding(
    funding_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("funding.approve"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    funding = await _load_funding_or_404(db, funding_id, for_update=True)
    route = f"/admin/fundings/{funding_id}/approve"
    request_hash = _request_hash({})
    replay = await _funding_idempotency_replay(
        db,
        route=route,
        actor_id=user.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        return await _load_funding_or_404(db, funding_id)

    services.transition_funding(db, funding, "APPROVED_FOR_FUNDING", user)
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body={"funding_id": str(funding.id)},
        )
    )
    await db.commit()
    await db.refresh(funding)
    return funding


@router.post(
    "/admin/fundings/{funding_id}/funds-sent",
    response_model=schemas.FundingRead,
    tags=["admin", "funding"],
)
async def funding_funds_sent(
    funding_id: uuid.UUID,
    payload: schemas.FundingFundsSentInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("funding.funds_sent"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    funding = await _load_funding_or_404(db, funding_id, for_update=True)
    route = f"/admin/fundings/{funding_id}/funds-sent"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    replay = await _funding_idempotency_replay(
        db,
        route=route,
        actor_id=user.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        return await _load_funding_or_404(db, funding_id)

    if funding.status == "FUNDS_SENT":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "FUNDING_ALREADY_FUNDS_SENT",
                "from_status": funding.status,
                "to_status": "FUNDS_SENT",
            },
        )

    services.transition_funding(db, funding, "FUNDS_SENT", user)
    funding.provider_reference = payload.provider_reference
    funding.funds_sent_at = models.utcnow()
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body={"funding_id": str(funding.id)},
        )
    )
    await db.commit()
    await db.refresh(funding)
    return funding


@router.post(
    "/admin/fundings/{funding_id}/confirm",
    response_model=schemas.FundingRead,
    tags=["admin", "funding"],
)
async def confirm_funding(
    funding_id: uuid.UUID,
    payload: schemas.FundingConfirmInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("funding.confirm"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    funding = await _load_funding_or_404(db, funding_id, for_update=True)
    route = f"/admin/fundings/{funding_id}/confirm"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    replay = await _funding_idempotency_replay(
        db,
        route=route,
        actor_id=user.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        return await _load_funding_or_404(db, funding_id)

    if funding.status == "FUNDED":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "FUNDING_ALREADY_FUNDED",
                "from_status": funding.status,
                "to_status": "FUNDED",
            },
        )

    services.transition_funding(db, funding, "FUNDED", user)
    funding.funded_amount = payload.funded_amount
    funding.funding_confirmed_at = models.utcnow()
    expected_amount = payload.commission_expected_amount
    if expected_amount is None:
        expected_amount = (
            payload.funded_amount * payload.commission_rate_bps / 10_000
        )
    db.add(
        models.Commission(
            funding_id=funding.id,
            expected_amount=expected_amount,
            status="EXPECTED",
        )
    )
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body={"funding_id": str(funding.id)},
        )
    )
    await db.commit()
    await db.refresh(funding)
    return funding


@router.post(
    "/admin/fundings/{funding_id}/decline",
    response_model=schemas.FundingRead,
    tags=["admin", "funding"],
)
async def decline_funding(
    funding_id: uuid.UUID,
    payload: schemas.FundingDeclineInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("funding.approve"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    funding = await _load_funding_or_404(db, funding_id, for_update=True)
    route = f"/admin/fundings/{funding_id}/decline"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    replay = await _funding_idempotency_replay(
        db,
        route=route,
        actor_id=user.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        return await _load_funding_or_404(db, funding_id)

    services.transition_funding(db, funding, "DECLINED", user, reason=payload.reason)
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body={"funding_id": str(funding.id)},
        )
    )
    await db.commit()
    await db.refresh(funding)
    return funding


@router.post(
    "/admin/contracts/{contract_id}/void",
    response_model=schemas.ContractRead,
    tags=["admin", "funding"],
)
async def void_contract(
    contract_id: uuid.UUID,
    payload: schemas.ContractVoidInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("contract.void"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    contract = await _load_contract_or_404(db, contract_id, for_update=True)
    route = f"/admin/contracts/{contract_id}/void"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    replay = await _funding_idempotency_replay(
        db,
        route=route,
        actor_id=user.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        return await _load_contract_or_404(db, contract_id)

    if contract.status == "SENT" and contract.external_envelope_id:
        await ensure_provider_void_confirmed(
            db,
            contract,
            reason=payload.reason,
            adapter=esign_adapter(),
        )
    services.transition_contract(db, contract, "VOIDED", user, reason=payload.reason)
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body={"contract_id": str(contract.id)},
        )
    )
    await db.commit()
    await db.refresh(contract)
    return contract


@router.get(
    "/admin/commissions",
    response_model=list[schemas.CommissionRead],
    tags=["admin", "funding"],
)
async def admin_commissions(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    return list(
        (
            await db.scalars(
                select(models.Commission).order_by(models.Commission.created_at.desc())
            )
        ).all()
    )


@router.get(
    "/admin/renewals",
    response_model=list[schemas.RenewalRead],
    tags=["admin", "funding"],
)
async def admin_renewals(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    return list(
        (
            await db.scalars(
                select(models.RenewalOpportunity).order_by(
                    models.RenewalOpportunity.created_at.desc()
                )
            )
        ).all()
    )


async def _load_renewal_or_404(
    db: AsyncSession, renewal_id: uuid.UUID, *, for_update: bool = False
) -> models.RenewalOpportunity:
    query = select(models.RenewalOpportunity).where(models.RenewalOpportunity.id == renewal_id)
    if for_update:
        query = query.with_for_update()
    renewal = await db.scalar(query)
    if renewal is None:
        raise HTTPException(status_code=404, detail="Renewal opportunity not found")
    return renewal


@router.post(
    "/admin/renewal-opportunities/{renewal_id}/status",
    response_model=schemas.RenewalRead,
    tags=["admin", "funding"],
)
async def update_renewal_status(
    renewal_id: uuid.UUID,
    payload: schemas.RenewalStatusInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("renewal.status.update"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    renewal = await _load_renewal_or_404(db, renewal_id, for_update=True)
    route = f"/admin/renewal-opportunities/{renewal_id}/status"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    replay = await _funding_idempotency_replay(
        db,
        route=route,
        actor_id=user.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        return await _load_renewal_or_404(db, renewal_id)

    services.transition_renewal_status(
        db, renewal, payload.status, user, reason=payload.reason
    )
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body={"renewal_id": str(renewal.id)},
        )
    )
    await db.commit()
    await db.refresh(renewal)
    return renewal


@router.get(
    "/admin/complaints",
    response_model=list[schemas.ComplaintRead],
    tags=["admin", "complaints"],
)
async def admin_complaints(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    return list(
        (
            await db.scalars(select(models.Complaint).order_by(models.Complaint.created_at.desc()))
        ).all()
    )


@router.get("/admin/integration-events", tags=["admin", "integrations"])
async def admin_integration_events(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    items = (
        await db.scalars(
            select(models.IntegrationEvent).order_by(models.IntegrationEvent.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "provider": item.provider,
            "event_type": item.event_type,
            "aggregate_id": str(item.aggregate_id),
            "status": item.status,
            "attempts": item.attempts,
            "external_id": item.external_id,
            "last_error": item.last_error,
            "created_at": item.created_at,
        }
        for item in items
    ]


@router.get(
    "/admin/affiliates",
    response_model=list[schemas.AffiliateRead],
    tags=["admin", "affiliates"],
)
async def admin_affiliates(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    return list((await db.scalars(select(models.Affiliate).order_by(models.Affiliate.name))).all())


@router.post(
    "/admin/affiliates",
    response_model=schemas.AffiliateRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin", "affiliates"],
)
async def create_affiliate(
    payload: schemas.AffiliateInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    existing = await db.scalar(
        select(models.Affiliate).where(models.Affiliate.tracking_code == payload.tracking_code)
    )
    if existing:
        raise HTTPException(status_code=409, detail="Tracking code already exists")
    item = models.Affiliate(**payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/admin/reconciliation-runs", tags=["admin", "reconciliation"])
async def reconciliation_runs(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    items = (
        await db.scalars(
            select(models.ReconciliationRun).order_by(models.ReconciliationRun.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "provider": item.provider,
            "status": item.status,
            "checked": item.checked,
            "mismatches": item.mismatches,
            "created_at": item.created_at,
            "completed_at": item.completed_at,
        }
        for item in items
    ]


@router.get(
    "/admin/reconciliation-runs/{run_id}/items",
    tags=["admin", "reconciliation"],
)
async def reconciliation_items(
    run_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    run = await db.get(models.ReconciliationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    items = (
        await db.scalars(
            select(models.ReconciliationItem)
            .where(models.ReconciliationItem.run_id == run_id)
            .order_by(models.ReconciliationItem.created_at)
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "resource_type": item.resource_type,
            "resource_id": item.resource_id,
            "status": item.status,
            "details": item.details,
        }
        for item in items
    ]


@router.post(
    "/admin/applications/{application_id}/fraud-assessments",
    response_model=schemas.FraudAssessmentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin", "fraud"],
)
async def run_fraud_assessment(
    application_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("fraud.run"))],
):
    application = await services.get_authorized_application(db, application_id, user, write=True)
    assessment = await domain_logic.evaluate_fraud(db, application)
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="FRAUD_ASSESSMENT_RUN",
            resource_type="application",
            resource_id=str(application.id),
            details={
                "assessment_id": str(assessment.id),
                "decision": assessment.decision,
                "score": assessment.score,
            },
        )
    )
    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.get(
    "/admin/underwriting/reviews",
    response_model=list[schemas.UnderwritingReviewRead],
    tags=["admin", "underwriting"],
)
async def underwriting_reviews(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("underwriting.review"))],
):
    return list(
        (
            await db.scalars(
                select(models.UnderwritingReview)
                .order_by(models.UnderwritingReview.created_at.desc())
                .limit(500)
            )
        ).all()
    )


@router.post(
    "/admin/applications/{application_id}/underwriting/reviews",
    response_model=schemas.UnderwritingReviewRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin", "underwriting"],
)
async def create_underwriting_review(
    application_id: uuid.UUID,
    payload: schemas.UnderwritingReviewInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("underwriting.review"))],
    request: Request,
):
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key is not None and not 8 <= len(idempotency_key) <= 160:
        raise HTTPException(status_code=422, detail="Invalid Idempotency-Key length")
    application = await services.get_authorized_application(
        db, application_id, user, write=True, lock_for_update=True
    )
    route = f"/admin/applications/{application_id}/underwriting/reviews"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    if idempotency_key is not None:
        replay = await _funding_idempotency_replay(
            db,
            route=route,
            actor_id=user.subject,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            review = await db.get(
                models.UnderwritingReview,
                uuid.UUID(replay.response_body["review_id"]),
            )
            if review is None:
                raise HTTPException(status_code=409, detail="Stored replay target is unavailable")
            return review
    review = await domain_logic.create_underwriting_review(db, application, payload, user)
    if idempotency_key is not None:
        db.add(
            models.IdempotencyRecord(
                key=idempotency_key,
                actor_id=user.subject,
                route=route,
                request_hash=request_hash,
                response_status=201,
                response_body={"review_id": str(review.id)},
            )
        )
    await db.commit()
    await db.refresh(review)
    return review


@router.get(
    "/admin/commissions/{commission_id}/splits",
    response_model=list[schemas.CommissionSplitRead],
    tags=["admin", "funding"],
)
async def commission_splits(
    commission_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("commission.read"))],
):
    if await db.get(models.Commission, commission_id) is None:
        raise HTTPException(status_code=404, detail="Commission not found")
    return list(
        (
            await db.scalars(
                select(models.CommissionSplit)
                .where(models.CommissionSplit.commission_id == commission_id)
                .order_by(models.CommissionSplit.created_at)
            )
        ).all()
    )


@router.get(
    "/admin/commissions/{commission_id}/adjustments",
    response_model=list[schemas.CommissionAdjustmentRead],
    tags=["admin", "funding"],
)
async def commission_adjustments(
    commission_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("commission.read"))],
):
    if await db.get(models.Commission, commission_id) is None:
        raise HTTPException(status_code=404, detail="Commission not found")
    return list(
        (
            await db.scalars(
                select(models.CommissionAdjustment)
                .where(models.CommissionAdjustment.commission_id == commission_id)
                .order_by(models.CommissionAdjustment.created_at)
            )
        ).all()
    )


@router.post(
    "/admin/commissions/{commission_id}/adjustments",
    response_model=schemas.CommissionAdjustmentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin", "funding"],
)
async def create_commission_adjustment(
    commission_id: uuid.UUID,
    payload: schemas.CommissionAdjustmentInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("commission.adjust"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    if payload.amount == 0:
        raise HTTPException(
            status_code=422,
            detail="Adjustment amount must be non-zero",
        )
    route = f"/admin/commissions/{commission_id}/adjustments"
    request_hash = hashlib.sha256(
        json.dumps(
            payload.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    commission = await _load_commission_or_404(db, commission_id)
    replay = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == user.subject,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if replay:
        if replay.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key payload conflict")
        replay_adjustment = await db.get(
            models.CommissionAdjustment, uuid.UUID(replay.response_body["adjustment_id"])
        )
        if replay_adjustment is None:
            raise HTTPException(status_code=409, detail="Stored replay target is unavailable")
        return replay_adjustment

    current_net = await _net_expected_amount(db, commission)
    adjusted_net = current_net + payload.amount
    split_total = await db.scalar(
        select(func.coalesce(func.sum(models.CommissionSplit.amount), 0)).where(
            models.CommissionSplit.commission_id == commission_id
        )
    )
    if adjusted_net <= 0:
        raise HTTPException(status_code=422, detail="Adjustment would make net commission non-positive")
    if adjusted_net < commission.received_amount:
        raise HTTPException(status_code=422, detail="Adjustment would make receipts exceed net commission")
    if adjusted_net < split_total:
        raise HTTPException(status_code=422, detail="Adjustment would make splits exceed net commission")

    adjustment = models.CommissionAdjustment(
        commission_id=commission_id,
        adjustment_type=payload.adjustment_type,
        amount=payload.amount,
        reason=payload.reason,
        created_by=user.subject,
    )
    db.add(adjustment)
    if commission.received_amount >= adjusted_net:
        commission.status = "RECEIVED"
    elif commission.received_amount > 0:
        commission.status = "PARTIALLY_RECEIVED"
    else:
        commission.status = "EXPECTED"
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="COMMISSION_ADJUSTMENT_RECORDED",
            resource_type="commission",
            resource_id=str(commission_id),
            details={
                "adjustment_type": payload.adjustment_type,
                "amount": str(payload.amount),
            },
        )
    )
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=201,
            response_body={"adjustment_id": str(adjustment.id)},
        )
    )
    await db.commit()
    await db.refresh(adjustment)
    return adjustment


async def _load_commission_or_404(db: AsyncSession, commission_id: uuid.UUID) -> models.Commission:
    commission = await db.scalar(
        select(models.Commission)
        .where(models.Commission.id == commission_id)
        .with_for_update()
    )
    if commission is None:
        raise HTTPException(status_code=404, detail="Commission not found")
    return commission


async def _net_expected_amount(db: AsyncSession, commission: models.Commission):
    adjustments_total = await db.scalar(
        select(func.coalesce(func.sum(models.CommissionAdjustment.amount), 0)).where(
            models.CommissionAdjustment.commission_id == commission.id
        )
    )
    return commission.expected_amount + adjustments_total


@router.post(
    "/admin/commissions/{commission_id}/receipts",
    response_model=schemas.CommissionRead,
    tags=["admin", "funding"],
)
async def record_commission_receipt(
    commission_id: uuid.UUID,
    payload: schemas.CommissionReceiptInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("commission.receipt.record"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    commission = await _load_commission_or_404(db, commission_id)
    route = f"/admin/commissions/{commission_id}/receipts"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    replay = await _funding_idempotency_replay(
        db,
        route=route,
        actor_id=user.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        return await _load_commission_or_404(db, commission_id)

    net_expected = await _net_expected_amount(db, commission)
    if commission.received_amount + payload.amount > net_expected:
        raise HTTPException(
            status_code=422,
            detail=f"Receipt would exceed the commission's net expected amount ({net_expected}).",
        )
    commission.received_amount = commission.received_amount + payload.amount
    if commission.received_amount >= net_expected:
        commission.status = "RECEIVED"
    elif commission.received_amount > 0:
        commission.status = "PARTIALLY_RECEIVED"
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="COMMISSION_RECEIPT_RECORDED",
            resource_type="commission",
            resource_id=str(commission_id),
            details={
                "amount": str(payload.amount),
                "reference": payload.reference,
                "received_amount": str(commission.received_amount),
            },
        )
    )
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body={"commission_id": str(commission.id)},
        )
    )
    await db.commit()
    await db.refresh(commission)
    return commission


@router.post(
    "/admin/commissions/{commission_id}/splits",
    response_model=schemas.CommissionSplitRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin", "funding"],
)
async def create_commission_split(
    commission_id: uuid.UUID,
    payload: schemas.CommissionSplitInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("commission.split.manage"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    commission = await _load_commission_or_404(db, commission_id)
    route = f"/admin/commissions/{commission_id}/splits"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    replay = await _funding_idempotency_replay(
        db,
        route=route,
        actor_id=user.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        existing = await db.scalar(
            select(models.CommissionSplit).where(
                models.CommissionSplit.id == uuid.UUID(replay.response_body["split_id"])
            )
        )
        if existing is None:
            raise HTTPException(status_code=409, detail="Stored replay target is unavailable")
        return existing

    existing_total = await db.scalar(
        select(func.coalesce(func.sum(models.CommissionSplit.amount), 0)).where(
            models.CommissionSplit.commission_id == commission_id
        )
    )
    net_expected = await _net_expected_amount(db, commission)
    if existing_total + payload.amount > net_expected:
        raise HTTPException(
            status_code=422,
            detail=(
                "Split amounts would exceed the commission's net expected "
                f"amount ({net_expected})."
            ),
        )

    split = models.CommissionSplit(
        commission_id=commission_id,
        recipient_type=payload.recipient_type,
        recipient_reference=payload.recipient_reference,
        percentage=payload.percentage,
        amount=payload.amount,
        status="PENDING",
    )
    db.add(split)
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="COMMISSION_SPLIT_CREATED",
            resource_type="commission",
            resource_id=str(commission_id),
            details={
                "recipient_type": payload.recipient_type,
                "recipient_reference": payload.recipient_reference,
                "amount": str(payload.amount),
            },
        )
    )
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=201,
            response_body={"split_id": str(split.id)},
        )
    )
    await db.commit()
    await db.refresh(split)
    return split


@router.post(
    "/admin/commissions/{commission_id}/splits/{split_id}/mark-paid",
    response_model=schemas.CommissionSplitRead,
    tags=["admin", "funding"],
)
async def mark_commission_split_paid(
    commission_id: uuid.UUID,
    split_id: uuid.UUID,
    payload: schemas.CommissionSplitPaymentInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("commission.split.manage"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    """Record externally verified payout evidence; this never initiates a payout."""
    await _load_commission_or_404(db, commission_id)
    route = f"/admin/commissions/{commission_id}/splits/{split_id}/mark-paid"
    request_hash = _request_hash(payload.model_dump(mode="json"))
    await acquire_idempotency_lock(
        db,
        actor_id=user.subject,
        route=route,
        key=idempotency_key,
    )
    replay = await _funding_idempotency_replay(
        db,
        route=route,
        actor_id=user.subject,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay is not None:
        replay_split = await db.get(models.CommissionSplit, split_id)
        if replay_split is None or replay_split.commission_id != commission_id:
            raise HTTPException(status_code=409, detail="Stored replay target is unavailable")
        return replay_split

    split = await db.scalar(
        select(models.CommissionSplit)
        .where(
            models.CommissionSplit.id == split_id,
            models.CommissionSplit.commission_id == commission_id,
        )
        .with_for_update()
    )
    if split is None:
        raise HTTPException(status_code=404, detail="Commission split not found")
    if split.status != "PENDING":
        raise HTTPException(status_code=409, detail="Commission split is not pending")

    split.status = "PAID"
    split.paid_at = payload.paid_at
    split.payment_reference = payload.payment_reference
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="COMMISSION_SPLIT_PAYMENT_RECORDED",
            resource_type="commission_split",
            resource_id=str(split.id),
            details={
                "commission_id": str(commission_id),
                "paid_at": payload.paid_at.isoformat(),
                "payment_reference": payload.payment_reference,
            },
        )
    )
    await db.flush()
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body={"split_id": str(split.id)},
        )
    )
    await db.commit()
    await db.refresh(split)
    return split


@router.get(
    "/admin/sla-alerts",
    response_model=list[schemas.SLAAlertRead],
    tags=["admin", "operations"],
)
async def sla_alerts(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    return list(
        (
            await db.scalars(
                select(models.SLAAlert).order_by(models.SLAAlert.created_at.desc()).limit(500)
            )
        ).all()
    )


@router.get(
    "/admin/users",
    response_model=list[schemas.UserAccountRead],
    tags=["admin", "identity"],
)
async def user_accounts(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("user.read"))],
):
    return list(
        (
            await db.scalars(
                select(models.UserAccount).order_by(models.UserAccount.created_at.desc()).limit(500)
            )
        ).all()
    )


@router.get("/admin/catalog/leads", tags=["admin", "catalog"])
async def catalog_leads(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    rows = (
        await db.scalars(select(models.Lead).order_by(models.Lead.created_at.desc()).limit(500))
    ).all()
    return [
        {
            "id": str(row.id),
            "business_name": row.business_name,
            "funding_amount": row.funding_amount,
            "monthly_revenue": row.monthly_revenue,
            "use_of_funds": row.use_of_funds,
            "status": row.status,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get(
    "/admin/catalog/applications",
    response_model=list[schemas.ApplicationRead],
    tags=["admin", "catalog"],
)
async def catalog_applications(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.read"))],
):
    return list(
        (
            await db.scalars(
                select(models.Application).order_by(models.Application.created_at.desc()).limit(500)
            )
        ).all()
    )


@router.get(
    "/admin/catalog/programs",
    response_model=list[schemas.ProgramRead],
    tags=["admin", "catalog"],
)
async def catalog_programs(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    return list(
        (
            await db.scalars(
                select(models.LenderProgram)
                .order_by(models.LenderProgram.created_at.desc())
                .limit(500)
            )
        ).all()
    )


@router.get(
    "/admin/catalog/submissions",
    response_model=list[schemas.LenderSubmissionRead],
    tags=["admin", "catalog"],
)
async def catalog_submissions(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.read"))],
):
    return list(
        (
            await db.scalars(
                select(models.LenderSubmission)
                .order_by(models.LenderSubmission.created_at.desc())
                .limit(500)
            )
        ).all()
    )


@router.get(
    "/admin/catalog/offers",
    response_model=list[schemas.OfferRead],
    tags=["admin", "catalog"],
)
async def catalog_offers(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.read"))],
):
    return list(
        (
            await db.scalars(
                select(models.Offer).order_by(models.Offer.created_at.desc()).limit(500)
            )
        ).all()
    )


@router.get(
    "/admin/catalog/matches",
    response_model=list[schemas.MatchRead],
    tags=["admin", "catalog"],
)
async def catalog_matches(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.read"))],
):
    return list(
        (
            await db.scalars(
                select(models.ApplicationMatch)
                .order_by(models.ApplicationMatch.created_at.desc())
                .limit(500)
            )
        ).all()
    )


@router.get(
    "/admin/provider-adapters",
    response_model=list[schemas.ProviderAdapterStatus],
    tags=["admin", "integrations"],
)
async def provider_adapters(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("capability.read"))],
):
    capabilities = await services.effective_capabilities(db)
    capability_by_provider = {
        "middleware": "crm.write", "crm": "crm.write", "bank": "bank.live_connection",
        "kyb": "kyb.live_verification", "credit": "credit.live_pull",
        "lender": "lenders.live_submission", "esign": "esign.live_send",
        "email": "communications.live_email", "sms": "communications.live_sms",
    }
    return [
        schemas.ProviderAdapterStatus(
            provider_type=row.provider_type,
            provider=row.provider,
            selected=row.selected,
            configured=row.configured and (
                capability_by_provider.get(row.provider_type) is None
                or capabilities.get(capability_by_provider[row.provider_type], False)
            ),
        )
        for row in provider_statuses()
    ]


@router.get(
    "/admin/applications/{application_id}/adverse-action-notices",
    response_model=list[schemas.AdverseActionNoticeRead],
    tags=["admin", "compliance"],
)
async def list_adverse_action_notices(
    application_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.read"))],
):
    return list(
        (
            await db.scalars(
                select(compliance_models.AdverseActionNotice)
                .where(compliance_models.AdverseActionNotice.application_id == application_id)
                .order_by(compliance_models.AdverseActionNotice.created_at.desc())
            )
        ).all()
    )


@router.get(
    "/admin/offers/{offer_id}/commercial-financing-disclosure",
    response_model=schemas.CommercialFinancingDisclosureRead,
    tags=["admin", "compliance"],
)
async def get_commercial_financing_disclosure(
    offer_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.read"))],
):
    disclosure = await compliance_service.get_offer_disclosure(db, offer_id)
    if disclosure is None:
        raise HTTPException(status_code=404, detail="Disclosure not found")
    return disclosure


@router.post(
    "/admin/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
    response_model=schemas.CommercialFinancingDisclosureRead,
    tags=["admin", "compliance"],
)
async def acknowledge_commercial_financing_disclosure(
    offer_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("application.edit"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    from app.compliance_routes import _acknowledge_disclosure, _disclosure_for_offer

    disclosure = await _disclosure_for_offer(db, offer_id, lock=True)
    return await _acknowledge_disclosure(
        db=db,
        disclosure=disclosure,
        user=user,
        idempotency_key=idempotency_key,
        route=f"/admin/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
    )


@router.post(
    "/admin/commission-tax-records/generate",
    response_model=list[schemas.CommissionTaxRecordRead],
    tags=["admin", "compliance"],
)
async def generate_commission_tax_records_endpoint(
    tax_year: int,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("commission.receipt.record"))],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    from app.compliance_routes import generate_tax_records

    return await generate_tax_records(tax_year, db, user, idempotency_key)


@router.get(
    "/admin/commission-tax-records",
    response_model=list[schemas.CommissionTaxRecordRead],
    tags=["admin", "compliance"],
)
async def list_commission_tax_records(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("commission.receipt.record"))],
    tax_year: int | None = None,
):
    statement = select(compliance_models.CommissionTaxRecord)
    if tax_year is not None:
        statement = statement.where(compliance_models.CommissionTaxRecord.tax_year == tax_year)
    return list(
        (
            await db.scalars(
                statement.order_by(compliance_models.CommissionTaxRecord.total_amount.desc())
            )
        ).all()
    )


@router.patch(
    "/admin/commission-tax-records/{record_id}/tin",
    response_model=schemas.CommissionTaxRecordRead,
    tags=["admin", "compliance"],
)
async def set_commission_tax_record_tin(
    record_id: uuid.UUID,
    payload: schemas.CommissionTaxRecordTinInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("commission.receipt.record"))],
):
    from app.compliance_routes import set_tax_record_tin

    return await set_tax_record_tin(record_id, payload, db, user)
