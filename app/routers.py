import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas, services
from app.auth import Principal, current_principal, require_permission
from app.db import get_db


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
    item.status = models.ApplicationStatus.APPLICATION_IN_PROGRESS
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
    return await services.match(db, application_id)


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
async def accept_offer(offer_id: uuid.UUID, db: Db, user: User):
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
        models.OutboxEvent(
            event_type="OfferAccepted",
            aggregate_id=offer.id,
            payload={"offer_id": str(offer.id)},
            idempotency_key=f"OfferAccepted:{offer.id}:{offer.version}",
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
    application.status = models.ApplicationStatus.OFFERS_AVAILABLE
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
