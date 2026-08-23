import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import banking, domain_logic, models, schemas, services
from app.auth import Principal, current_principal, require_permission
from app.db import get_db
from app.integrations.base import ProviderError
from app.integrations.plaid import PlaidAdapter
from app.integrations.registry import provider_statuses


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


@router.post(
    "/public/prequalifications",
    response_model=schemas.LeadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["public"],
)
async def prequalify(
    payload: schemas.PrequalificationInput,
    request: Request,
    db: Db,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    return await services.create_lead(
        db,
        payload,
        idempotency_key or str(uuid.uuid4()),
        request.headers.get("X-Request-ID", str(uuid.uuid4())),
    )


@router.get("/me", tags=["identity"])
async def me(user: User):
    return {"id": user.subject, "roles": sorted(user.roles), "permissions": sorted(user.permissions)}


@router.get("/me/capabilities", tags=["identity"])
async def my_capabilities(db: Db, user: User):
    return await services.effective_capabilities(db)


@router.post("/applications", response_model=schemas.ApplicationRead, tags=["applications"])
async def create_application(payload: schemas.ApplicationCreate, db: Db, user: User):
    existing = await db.scalar(
        select(models.Application).where(models.Application.lead_id == payload.lead_id)
    )
    if existing:
        if "BORROWER" in user.roles and not existing.borrower_subject:
            existing.borrower_subject = user.subject
            await db.commit()
        services.authorize_application(existing, user)
        return existing
    lead = await db.get(models.Lead, payload.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    item = models.Application(
        lead_id=lead.id,
        requested_amount=lead.funding_amount,
        monthly_revenue=lead.monthly_revenue,
        time_in_business_months=lead.time_in_business_months,
        borrower_subject=user.subject if "BORROWER" in user.roles else None,
    )
    lead.status = models.LeadStatus.APPLICATION_STARTED
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.post(
    "/applications/from-lead/{lead_id}",
    response_model=schemas.ApplicationRead,
    tags=["applications"],
)
async def create_application_from_lead(lead_id: uuid.UUID, db: Db, user: User):
    return await create_application(schemas.ApplicationCreate(lead_id=lead_id), db, user)


@router.get(
    "/applications/{application_id}",
    response_model=schemas.ApplicationRead,
    tags=["applications"],
)
async def get_application(application_id: uuid.UUID, db: Db, user: User):
    return await services.get_authorized_application(db, application_id, user)


@router.patch(
    "/applications/{application_id}",
    response_model=schemas.ApplicationRead,
    tags=["applications"],
)
async def update_application(
    application_id: uuid.UUID,
    payload: schemas.ApplicationUpdate,
    db: Db,
    user: User,
):
    item = await services.get_authorized_application(
        db, application_id, user, write=True
    )
    if payload.version != item.version:
        raise HTTPException(status_code=409, detail="Application version conflict")
    for name, value in payload.model_dump(exclude={"version"}, exclude_none=True).items():
        setattr(item, name, value)
    item.version += 1
    if item.status == models.ApplicationStatus.APPLICATION_STARTED:
        services.transition_application(
            db,
            item,
            models.ApplicationStatus.APPLICATION_IN_PROGRESS,
            user,
            reason="Application fields updated",
        )
    item.completion_percentage = min(90, item.completion_percentage + 10)
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/applications/{application_id}/requirements", tags=["applications"])
async def requirements(application_id: uuid.UUID, db: Db, user: User):
    item = await services.get_authorized_application(db, application_id, user)
    return await services.application_requirements(db, item)



@router.post(
    "/applications/{application_id}/match",
    response_model=list[schemas.MatchRead],
    tags=["matching"],
)
async def match_application(application_id: uuid.UUID, db: Db, user: User):
    if "*" not in user.permissions and "matching.run" not in user.permissions:
        raise HTTPException(status_code=403, detail="Permission denied")
    return await services.match(db, application_id, user)


@router.get(
    "/applications/{application_id}/matches",
    response_model=list[schemas.MatchRead],
    tags=["matching"],
)
async def matches(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.ApplicationMatch)
                .where(models.ApplicationMatch.application_id == application_id)
                .order_by(models.ApplicationMatch.score.desc())
            )
        ).all()
    )


@router.get(
    "/applications/{application_id}/offers",
    response_model=list[schemas.OfferRead],
    tags=["offers"],
)
async def offers(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.Offer).where(models.Offer.application_id == application_id)
            )
        ).all()
    )


@router.post(
    "/offers/{offer_id}/accept",
    response_model=schemas.OfferRead,
    tags=["offers"],
)
async def accept_offer(
    offer_id: uuid.UUID,
    db: Db,
    user: User,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
):
    route = f"/offers/{offer_id}/accept"
    request_hash = hashlib.sha256(str(offer_id).encode()).hexdigest()
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
        replay_offer = await db.get(
            models.Offer, uuid.UUID(replay.response_body["offer_id"])
        )
        if replay_offer is None:
            raise HTTPException(status_code=409, detail="Stored replay target is unavailable")
        return replay_offer

    offer = await db.get(models.Offer, offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    application = await services.get_authorized_application(
        db, offer.application_id, user, write=True
    )
    if (
        "*" not in user.permissions
        and "offer.accept.own" not in user.permissions
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    if offer.status != "AVAILABLE":
        raise HTTPException(status_code=409, detail="Offer is not available")
    if offer.expires_at:
        expires_at = offer.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            offer.status = "EXPIRED"
            offer.version += 1
            await db.commit()
            raise HTTPException(status_code=409, detail="Offer has expired")
    existing_funding = await db.scalar(
        select(models.Funding).where(
            models.Funding.application_id == application.id
        )
    )
    if existing_funding:
        raise HTTPException(status_code=409, detail="An offer is already accepted")
    offer.status = "ACCEPTED"
    offer.version += 1
    services.transition_application(
        db,
        application,
        models.ApplicationStatus.OFFER_ACCEPTED,
        user,
        reason="Borrower accepted offer",
    )
    db.add(
        models.Funding(
            application_id=application.id,
            offer_id=offer.id,
            status="CONDITIONS_PENDING",
            approved_amount=offer.amount,
        )
    )
    db.add(
        models.OutboxEvent(
            event_type="OfferAccepted",
            aggregate_id=offer.id,
            payload={"offer_id": str(offer.id)},
            idempotency_key=f"OfferAccepted:{offer.id}:{offer.version}",
        )
    )
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=200,
            response_body={"offer_id": str(offer.id), "status": "ACCEPTED"},
        )
    )
    await db.commit()
    await db.refresh(offer)
    return offer


@router.post(
    "/lenders/{lender_id}/programs",
    response_model=schemas.ProgramRead,
    tags=["lenders"],
)
async def create_program(
    lender_id: uuid.UUID,
    payload: schemas.ProgramInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("program.manage"))],
):
    if lender_id != payload.lender_id:
        raise HTTPException(status_code=422, detail="Lender ID mismatch")
    if (
        "*" not in user.permissions
        and user.organization_id != str(lender_id)
    ):
        raise HTTPException(status_code=403, detail="Lender organization mismatch")
    item = models.LenderProgram(**payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.post(
    "/lender/applications/{application_id}/offers",
    response_model=schemas.OfferRead,
    tags=["lender"],
)
async def lender_offer(
    application_id: uuid.UUID,
    payload: schemas.OfferInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("offer.create"))],
):
    if payload.application_id != application_id:
        raise HTTPException(status_code=422, detail="Application ID mismatch")
    if (
        "*" not in user.permissions
        and user.organization_id != str(payload.lender_id)
    ):
        raise HTTPException(status_code=403, detail="Lender organization mismatch")
    item = models.Offer(**payload.model_dump())
    db.add(item)
    application = await db.get(models.Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    services.transition_application(
        db,
        application,
        models.ApplicationStatus.OFFERS_AVAILABLE,
        user,
        reason="Lender created offer",
    )
    await db.commit()
    await db.refresh(item)
    return item


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
            select(models.CapabilityFlag)
            .order_by(models.CapabilityFlag.environment, models.CapabilityFlag.key)
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
            select(models.ProviderConnection)
            .order_by(
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


@router.get("/borrower/dashboard", tags=["borrower"])
async def borrower_dashboard(db: Db, user: User):
    items = list(
        (
            await db.scalars(
                select(models.Application)
                .where(models.Application.borrower_subject == user.subject)
                .order_by(models.Application.updated_at.desc())
            )
        ).all()
    )
    active = items[0] if items else None
    return {
        "applications": items,
        "active_application": active,
        "requirements": (
            await services.application_requirements(db, active) if active else None
        ),
    }


@router.get(
    "/borrower/applications",
    response_model=list[schemas.ApplicationRead],
    tags=["borrower"],
)
async def borrower_applications(db: Db, user: User):
    return list(
        (
            await db.scalars(
                select(models.Application)
                .where(models.Application.borrower_subject == user.subject)
                .order_by(models.Application.updated_at.desc())
            )
        ).all()
    )


@router.get("/applications/{application_id}/timeline", tags=["applications"])
async def application_timeline(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.ApplicationStatusHistory)
                .where(models.ApplicationStatusHistory.application_id == application_id)
                .order_by(models.ApplicationStatusHistory.created_at)
            )
        ).all()
    )


@router.get(
    "/applications/{application_id}/business",
    response_model=schemas.BusinessRead | None,
    tags=["applications"],
)
async def get_business(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return await db.scalar(
        select(models.Business).where(models.Business.application_id == application_id)
    )


@router.put(
    "/applications/{application_id}/business",
    response_model=schemas.BusinessRead,
    tags=["applications"],
)
async def save_business(
    application_id: uuid.UUID,
    payload: schemas.BusinessInput,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user, write=True)
    item = await db.scalar(
        select(models.Business).where(models.Business.application_id == application_id)
    )
    values = payload.model_dump()
    if item is None:
        item = models.Business(application_id=application_id, **values)
        db.add(item)
    else:
        for name, value in values.items():
            setattr(item, name, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/applications/{application_id}/financial-profile",
    response_model=schemas.FinancialProfileRead | None,
    tags=["applications"],
)
async def get_financial_profile(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return await db.scalar(
        select(models.FinancialProfile).where(
            models.FinancialProfile.application_id == application_id
        )
    )


@router.put(
    "/applications/{application_id}/financial-profile",
    response_model=schemas.FinancialProfileRead,
    tags=["applications"],
)
async def save_financial_profile(
    application_id: uuid.UUID,
    payload: schemas.FinancialProfileInput,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user, write=True)
    item = await db.scalar(
        select(models.FinancialProfile).where(
            models.FinancialProfile.application_id == application_id
        )
    )
    values = payload.model_dump()
    if item is None:
        item = models.FinancialProfile(application_id=application_id, **values)
        db.add(item)
    else:
        for name, value in values.items():
            setattr(item, name, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/applications/{application_id}/owners",
    response_model=list[schemas.OwnerRead],
    tags=["applications"],
)
async def list_owners(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.Owner)
                .where(models.Owner.application_id == application_id)
                .order_by(models.Owner.created_at)
            )
        ).all()
    )


@router.post(
    "/applications/{application_id}/owners",
    response_model=schemas.OwnerRead,
    status_code=status.HTTP_201_CREATED,
    tags=["applications"],
)
async def add_owner(
    application_id: uuid.UUID,
    payload: schemas.OwnerInput,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user, write=True)
    values = payload.model_dump()
    values["email"] = str(payload.email) if payload.email else None
    item = models.Owner(application_id=application_id, **values)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch(
    "/applications/{application_id}/owners/{owner_id}",
    response_model=schemas.OwnerRead,
    tags=["applications"],
)
async def update_owner(
    application_id: uuid.UUID,
    owner_id: uuid.UUID,
    payload: schemas.OwnerInput,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user, write=True)
    item = await db.get(models.Owner, owner_id)
    if item is None or item.application_id != application_id:
        raise HTTPException(status_code=404, detail="Owner not found")
    values = payload.model_dump()
    values["email"] = str(payload.email) if payload.email else None
    for name, value in values.items():
        setattr(item, name, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete(
    "/applications/{application_id}/owners/{owner_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["applications"],
)
async def delete_owner(
    application_id: uuid.UUID,
    owner_id: uuid.UUID,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user, write=True)
    item = await db.get(models.Owner, owner_id)
    if item is None or item.application_id != application_id:
        raise HTTPException(status_code=404, detail="Owner not found")
    await db.delete(item)
    await db.commit()


@router.post("/applications/{application_id}/submit", tags=["applications"])
async def submit_application(application_id: uuid.UUID, db: Db, user: User):
    item = await services.get_authorized_application(
        db, application_id, user, write=True
    )
    if (
        "*" not in user.permissions
        and "application.submit.own" not in user.permissions
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    requirement_state = await services.application_requirements(db, item)
    if not requirement_state["ready_to_submit"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "APPLICATION_INCOMPLETE", **requirement_state},
        )
    services.transition_application(
        db,
        item,
        models.ApplicationStatus.READY_FOR_MATCHING,
        user,
        reason="Application requirements completed",
    )
    db.add(
        models.OutboxEvent(
            event_type="ApplicationSubmitted",
            aggregate_id=item.id,
            payload={"application_id": str(item.id)},
            idempotency_key=f"ApplicationSubmitted:{item.id}:{item.version}",
        )
    )
    await db.commit()
    return {"status": item.status, "version": item.version}


def lender_scope(user: Principal) -> uuid.UUID | None:
    if "*" in user.permissions:
        return None
    if not user.organization_id:
        raise HTTPException(status_code=403, detail="Lender organization is not mapped")
    try:
        return uuid.UUID(user.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail="Invalid lender organization mapping"
        ) from exc


@router.post(
    "/applications/{application_id}/credit-authorizations",
    response_model=schemas.CreditAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
    tags=["credit"],
)
async def authorize_credit(
    application_id: uuid.UUID,
    payload: schemas.CreditAuthorizationInput,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user, write=True)
    if (
        "*" not in user.permissions
        and "credit.authorize.own" not in user.permissions
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    existing = await db.scalar(
        select(models.CreditAuthorization).where(
            models.CreditAuthorization.application_id == application_id,
            models.CreditAuthorization.authorization_version
            == payload.authorization_version,
        )
    )
    if existing:
        if existing.document_hash != payload.document_hash:
            raise HTTPException(
                status_code=409,
                detail="Authorization version already accepted with another hash",
            )
        return existing
    item = models.CreditAuthorization(
        application_id=application_id,
        authorization_version=payload.authorization_version,
        document_hash=payload.document_hash,
        accepted_by=user.subject,
    )
    db.add(item)
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="CREDIT_AUTHORIZATION_ACCEPTED",
            resource_type="application",
            resource_id=str(application_id),
            details={
                "authorization_version": payload.authorization_version,
                "document_hash": payload.document_hash,
            },
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/applications/{application_id}/credit-authorizations",
    response_model=list[schemas.CreditAuthorizationRead],
    tags=["credit"],
)
async def credit_authorizations(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.CreditAuthorization)
                .where(models.CreditAuthorization.application_id == application_id)
                .order_by(models.CreditAuthorization.accepted_at.desc())
            )
        ).all()
    )


@router.get(
    "/applications/{application_id}/conditions",
    response_model=list[schemas.ConditionRead],
    tags=["underwriting"],
)
async def application_conditions(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    if (
        "*" not in user.permissions
        and "condition.read.own" not in user.permissions
        and "underwriting.review" not in user.permissions
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    return list(
        (
            await db.scalars(
                select(models.UnderwritingCondition)
                .where(
                    models.UnderwritingCondition.application_id == application_id
                )
                .order_by(models.UnderwritingCondition.created_at.desc())
            )
        ).all()
    )


@router.post(
    "/applications/{application_id}/complaints",
    response_model=schemas.ComplaintRead,
    status_code=status.HTTP_201_CREATED,
    tags=["complaints"],
)
async def create_application_complaint(
    application_id: uuid.UUID,
    payload: schemas.ComplaintInput,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user)
    if (
        "*" not in user.permissions
        and "complaint.create.own" not in user.permissions
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    item = models.Complaint(
        application_id=application_id,
        created_by=user.subject,
        **payload.model_dump(),
    )
    db.add(item)
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="COMPLAINT_CREATED",
            resource_type="application",
            resource_id=str(application_id),
            details={"category": payload.category, "priority": payload.priority},
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/applications/{application_id}/complaints",
    response_model=list[schemas.ComplaintRead],
    tags=["complaints"],
)
async def application_complaints(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.Complaint)
                .where(models.Complaint.application_id == application_id)
                .order_by(models.Complaint.created_at.desc())
            )
        ).all()
    )


@router.post(
    "/admin/applications/{application_id}/prepare-matched-submissions",
    response_model=list[schemas.LenderSubmissionRead],
    tags=["admin", "lender"],
)
async def prepare_matched_submissions(
    application_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("matching.run"))],
):
    application = await db.get(models.Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    matches = list(
        (
            await db.scalars(
                select(models.ApplicationMatch).where(
                    models.ApplicationMatch.application_id == application_id,
                    models.ApplicationMatch.eligible,
                )
            )
        ).all()
    )
    if not matches:
        raise HTTPException(status_code=409, detail="No eligible matches exist")
    prepared: list[models.LenderSubmission] = []
    for match in matches:
        existing = await db.scalar(
            select(models.LenderSubmission).where(
                models.LenderSubmission.application_id == application_id,
                models.LenderSubmission.program_id == match.program_id,
                models.LenderSubmission.program_version
                == match.program_version,
            )
        )
        if existing:
            prepared.append(existing)
            continue
        item = models.LenderSubmission(
            application_id=application_id,
            lender_id=match.lender_id,
            program_id=match.program_id,
            program_version=match.program_version,
            status="DRAFT",
        )
        db.add(item)
        prepared.append(item)
    if application.status == models.ApplicationStatus.MATCHED:
        services.transition_application(
            db,
            application,
            models.ApplicationStatus.SUBMITTED_TO_LENDERS,
            user,
            reason="Matched lender submissions prepared",
        )
    await db.commit()
    for item in prepared:
        await db.refresh(item)
    return prepared


@router.get(
    "/lender/submissions",
    response_model=list[schemas.LenderSubmissionRead],
    tags=["lender"],
)
async def lender_submissions(
    db: Db,
    user: Annotated[
        Principal, Depends(require_permission("lender.submission.read"))
    ],
):
    lender_id = lender_scope(user)
    statement = select(models.LenderSubmission)
    if lender_id:
        statement = statement.where(models.LenderSubmission.lender_id == lender_id)
    return list(
        (
            await db.scalars(
                statement.order_by(models.LenderSubmission.created_at.desc())
            )
        ).all()
    )


async def authorized_submission(
    submission_id: uuid.UUID,
    db: AsyncSession,
    user: Principal,
) -> models.LenderSubmission:
    item = await db.get(models.LenderSubmission, submission_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    lender_id = lender_scope(user)
    if lender_id and item.lender_id != lender_id:
        raise HTTPException(status_code=403, detail="Lender organization mismatch")
    return item


@router.post(
    "/lender/submissions/{submission_id}/conditions",
    response_model=schemas.ConditionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["lender", "underwriting"],
)
async def create_condition(
    submission_id: uuid.UUID,
    payload: schemas.ConditionInput,
    db: Db,
    user: Annotated[
        Principal, Depends(require_permission("lender.condition.create"))
    ],
):
    submission = await authorized_submission(submission_id, db, user)
    item = models.UnderwritingCondition(
        submission_id=submission.id,
        application_id=submission.application_id,
        description=payload.description,
        status="BORROWER_ACTION_REQUIRED",
    )
    submission.status = "CONDITIONS"
    application = await db.get(models.Application, submission.application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status in {
        models.ApplicationStatus.SUBMITTED_TO_LENDERS,
        models.ApplicationStatus.UNDERWRITING,
    }:
        services.transition_application(
            db,
            application,
            models.ApplicationStatus.CONDITIONS_PENDING,
            user,
            reason="Lender requested an underwriting condition",
        )
    db.add(item)
    await db.flush()
    db.add(
        models.OutboxEvent(
            event_type="ConditionRequested",
            aggregate_id=submission.application_id,
            payload={
                "application_id": str(submission.application_id),
                "submission_id": str(submission.id),
            },
            idempotency_key=f"ConditionRequested:{item.id}",
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.post(
    "/lender/submissions/{submission_id}/offers",
    response_model=schemas.OfferRead,
    status_code=status.HTTP_201_CREATED,
    tags=["lender", "offers"],
)
async def create_submission_offer(
    submission_id: uuid.UUID,
    payload: schemas.OfferInput,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("offer.create"))],
):
    submission = await authorized_submission(submission_id, db, user)
    if payload.application_id != submission.application_id:
        raise HTTPException(status_code=422, detail="Application ID mismatch")
    if payload.lender_id != submission.lender_id:
        raise HTTPException(status_code=422, detail="Lender ID mismatch")
    item = models.Offer(**payload.model_dump())
    submission.status = "OFFERED"
    application = await db.get(models.Application, submission.application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    services.transition_application(
        db,
        application,
        models.ApplicationStatus.OFFERS_AVAILABLE,
        user,
        reason="Lender created offer from submission",
    )
    db.add(item)
    await db.flush()
    db.add(
        models.OutboxEvent(
            event_type="OfferReceived",
            aggregate_id=application.id,
            payload={"application_id": str(application.id), "offer_id": str(item.id)},
            idempotency_key=f"OfferReceived:{item.id}",
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/applications/{application_id}/funding",
    response_model=schemas.FundingRead | None,
    tags=["funding"],
)
async def application_funding(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return await db.scalar(
        select(models.Funding).where(models.Funding.application_id == application_id)
    )


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
        (
            await db.scalars(
                select(models.Funding).order_by(models.Funding.created_at.desc())
            )
        ).all()
    )


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
            await db.scalars(
                select(models.Complaint).order_by(models.Complaint.created_at.desc())
            )
        ).all()
    )


@router.get("/admin/integration-events", tags=["admin", "integrations"])
async def admin_integration_events(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    items = (
        await db.scalars(
            select(models.IntegrationEvent).order_by(
                models.IntegrationEvent.created_at.desc()
            )
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
    return list(
        (
            await db.scalars(
                select(models.Affiliate).order_by(models.Affiliate.name)
            )
        ).all()
    )


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
        select(models.Affiliate).where(
            models.Affiliate.tracking_code == payload.tracking_code
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Tracking code already exists")
    item = models.Affiliate(**payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/me/notification-preferences",
    response_model=schemas.NotificationPreferenceRead,
    tags=["identity", "communications"],
)
async def notification_preferences(db: Db, user: User):
    item = await db.scalar(
        select(models.NotificationPreference).where(
            models.NotificationPreference.subject == user.subject
        )
    )
    if item is None:
        item = models.NotificationPreference(subject=user.subject)
        db.add(item)
        await db.commit()
        await db.refresh(item)
    return item


@router.put(
    "/me/notification-preferences",
    response_model=schemas.NotificationPreferenceRead,
    tags=["identity", "communications"],
)
async def update_notification_preferences(
    payload: schemas.NotificationPreferenceInput,
    db: Db,
    user: User,
):
    item = await db.scalar(
        select(models.NotificationPreference).where(
            models.NotificationPreference.subject == user.subject
        )
    )
    if item is None:
        item = models.NotificationPreference(
            subject=user.subject,
            **payload.model_dump(),
        )
        db.add(item)
    else:
        for name, value in payload.model_dump().items():
            setattr(item, name, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.post(
    "/conditions/{condition_id}/submit",
    response_model=schemas.ConditionRead,
    tags=["underwriting"],
)
async def submit_condition(
    condition_id: uuid.UUID,
    db: Db,
    user: User,
):
    item = await db.get(models.UnderwritingCondition, condition_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Condition not found")
    await services.get_authorized_application(
        db, item.application_id, user, write=True
    )
    if item.status not in {"BORROWER_ACTION_REQUIRED", "REJECTED"}:
        raise HTTPException(
            status_code=409,
            detail="Condition cannot be submitted in its current state",
        )
    item.status = "SUBMITTED"
    db.add(
        models.OutboxEvent(
            event_type="ConditionSubmitted",
            aggregate_id=item.application_id,
            payload={
                "application_id": str(item.application_id),
                "condition_id": str(item.id),
            },
            idempotency_key=f"ConditionSubmitted:{item.id}:{item.updated_at}",
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


async def decide_condition(
    condition_id: uuid.UUID,
    decision: str,
    db: AsyncSession,
    user: Principal,
) -> models.UnderwritingCondition:
    item = await db.get(models.UnderwritingCondition, condition_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Condition not found")
    submission = await authorized_submission(item.submission_id, db, user)
    if item.status not in {
        "SUBMITTED",
        "BORROWER_ACTION_REQUIRED",
        "REJECTED",
    }:
        raise HTTPException(
            status_code=409,
            detail="Condition cannot be reviewed in its current state",
        )
    item.status = decision
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action=f"CONDITION_{decision}",
            resource_type="condition",
            resource_id=str(item.id),
            details={"submission_id": str(submission.id)},
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.post(
    "/lender/conditions/{condition_id}/approve",
    response_model=schemas.ConditionRead,
    tags=["lender", "underwriting"],
)
async def approve_condition(
    condition_id: uuid.UUID,
    db: Db,
    user: Annotated[
        Principal, Depends(require_permission("lender.condition.review"))
    ],
):
    return await decide_condition(condition_id, "SATISFIED", db, user)


@router.post(
    "/lender/conditions/{condition_id}/reject",
    response_model=schemas.ConditionRead,
    tags=["lender", "underwriting"],
)
async def reject_condition(
    condition_id: uuid.UUID,
    db: Db,
    user: Annotated[
        Principal, Depends(require_permission("lender.condition.review"))
    ],
):
    return await decide_condition(condition_id, "REJECTED", db, user)


@router.post(
    "/lender/conditions/{condition_id}/waive",
    response_model=schemas.ConditionRead,
    tags=["lender", "underwriting"],
)
async def waive_condition(
    condition_id: uuid.UUID,
    db: Db,
    user: Annotated[
        Principal, Depends(require_permission("lender.condition.review"))
    ],
):
    return await decide_condition(condition_id, "WAIVED", db, user)


@router.get("/admin/reconciliation-runs", tags=["admin", "reconciliation"])
async def reconciliation_runs(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    items = (
        await db.scalars(
            select(models.ReconciliationRun).order_by(
                models.ReconciliationRun.created_at.desc()
            )
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
    "/applications/{application_id}/requirement-snapshots",
    response_model=schemas.RequirementSnapshotRead,
    status_code=status.HTTP_201_CREATED,
    tags=["applications", "underwriting"],
)
async def create_requirement_snapshot(
    application_id: uuid.UUID,
    db: Db,
    user: Annotated[
        Principal, Depends(require_permission("underwriting.review"))
    ],
):
    application = await services.get_authorized_application(
        db, application_id, user
    )
    snapshot = await domain_logic.create_requirement_snapshot(db, application)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


@router.get(
    "/applications/{application_id}/requirement-snapshots",
    response_model=list[schemas.RequirementSnapshotRead],
    tags=["applications"],
)
async def requirement_snapshots(
    application_id: uuid.UUID,
    db: Db,
    user: User,
):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.RequirementSnapshot)
                .where(
                    models.RequirementSnapshot.application_id
                    == application_id
                )
                .order_by(models.RequirementSnapshot.created_at.desc())
            )
        ).all()
    )


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
    application = await services.get_authorized_application(
        db, application_id, user
    )
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
    user: Annotated[
        Principal, Depends(require_permission("underwriting.review"))
    ],
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
    user: Annotated[
        Principal, Depends(require_permission("underwriting.review"))
    ],
):
    application = await services.get_authorized_application(
        db, application_id, user
    )
    review = await domain_logic.create_underwriting_review(
        db, application, payload, user
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
    user: Annotated[
        Principal, Depends(require_permission("commission.read"))
    ],
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
    user: Annotated[
        Principal, Depends(require_permission("commission.read"))
    ],
):
    if await db.get(models.Commission, commission_id) is None:
        raise HTTPException(status_code=404, detail="Commission not found")
    return list(
        (
            await db.scalars(
                select(models.CommissionAdjustment)
                .where(
                    models.CommissionAdjustment.commission_id
                    == commission_id
                )
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
    user: Annotated[
        Principal, Depends(require_permission("commission.adjust"))
    ],
):
    if payload.amount == 0:
        raise HTTPException(
            status_code=422,
            detail="Adjustment amount must be non-zero",
        )
    if await db.get(models.Commission, commission_id) is None:
        raise HTTPException(status_code=404, detail="Commission not found")
    adjustment = models.CommissionAdjustment(
        commission_id=commission_id,
        adjustment_type=payload.adjustment_type,
        amount=payload.amount,
        reason=payload.reason,
        created_by=user.subject,
    )
    db.add(adjustment)
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
    await db.commit()
    await db.refresh(adjustment)
    return adjustment


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
                select(models.SLAAlert)
                .order_by(models.SLAAlert.created_at.desc())
                .limit(500)
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
                select(models.UserAccount)
                .order_by(models.UserAccount.created_at.desc())
                .limit(500)
            )
        ).all()
    )


@router.get("/admin/catalog/leads", tags=["admin", "catalog"])
async def catalog_leads(
    db: Db,
    user: Annotated[Principal, Depends(require_permission("lead.read"))],
):
    rows = (
        await db.scalars(
            select(models.Lead).order_by(models.Lead.created_at.desc()).limit(500)
        )
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
    user: Annotated[
        Principal, Depends(require_permission("application.read"))
    ],
):
    return list(
        (
            await db.scalars(
                select(models.Application)
                .order_by(models.Application.created_at.desc())
                .limit(500)
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
    user: Annotated[
        Principal, Depends(require_permission("application.read"))
    ],
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
    user: Annotated[
        Principal, Depends(require_permission("application.read"))
    ],
):
    return list(
        (
            await db.scalars(
                select(models.Offer)
                .order_by(models.Offer.created_at.desc())
                .limit(500)
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
    user: Annotated[
        Principal, Depends(require_permission("application.read"))
    ],
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
    application = await services.get_authorized_application(
        db, application_id, user, write=True
    )
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
    application = await services.get_authorized_application(
        db, application_id, user, write=True
    )
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
    application = await services.get_authorized_application(
        db, application_id, user, write=True
    )
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
                    models.BankConnection.id
                    == models.BankAccount.connection_id,
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


@router.get(
    "/admin/provider-adapters",
    response_model=list[schemas.ProviderAdapterStatus],
    tags=["admin", "integrations"],
)
async def provider_adapters(
    db: Db,
    user: Annotated[
        Principal, Depends(require_permission("capability.read"))
    ],
):
    capabilities = await services.effective_capabilities(db)
    return [
        schemas.ProviderAdapterStatus(
            provider_type=row.provider_type,
            provider=row.provider,
            selected=row.selected,
            configured=(
                row.configured
                and capabilities.get(
                    {
                        "bank": "bank.live_connection",
                        "kyb": "kyb.live_verification",
                        "credit": "credit.live_pull",
                        "lender": "lenders.live_submission",
                        "esign": "esign.live_send",
                        "email": "communications.live_email",
                        "sms": "communications.live_sms",
                    }.get(row.provider_type, ""),
                    False,
                )
            ),
        )
        for row in provider_statuses()
    ]


@router.post("/webhooks/plaid", tags=["provider-webhooks"])
async def plaid_webhook(
    request: Request,
    db: Db,
    plaid_verification: Annotated[
        str | None, Header(alias="Plaid-Verification")
    ] = None,
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
    event_code = str(
        payload.get("webhook_code")
        or payload.get("webhook_type")
        or "UNKNOWN"
    )
    item_id = str(payload.get("item_id") or "unknown")
    provider_event_id = str(
        payload.get("webhook_id")
        or f"{item_id}:{event_code}:{payload_hash[:24]}"
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
