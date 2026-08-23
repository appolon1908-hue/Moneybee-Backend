import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas, services
from app.auth import Principal, current_principal, require_permission
from app.db import get_db


router = APIRouter(prefix="/api/v1")
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


@router.post("/applications", response_model=schemas.ApplicationRead, tags=["applications"])
async def create_application(payload: schemas.ApplicationCreate, db: Db, user: User):
    existing = await db.scalar(
        select(models.Application).where(models.Application.lead_id == payload.lead_id)
    )
    if existing:
        return existing
    lead = await db.get(models.Lead, payload.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    item = models.Application(
        lead_id=lead.id,
        requested_amount=lead.funding_amount,
        monthly_revenue=lead.monthly_revenue,
        time_in_business_months=lead.time_in_business_months,
    )
    lead.status = models.LeadStatus.APPLICATION_STARTED
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get(
    "/applications/{application_id}",
    response_model=schemas.ApplicationRead,
    tags=["applications"],
)
async def get_application(application_id: uuid.UUID, db: Db, user: User):
    item = await db.get(models.Application, application_id)
    if not item:
        raise HTTPException(status_code=404, detail="Application not found")
    return item


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
    item = await db.get(models.Application, application_id)
    if not item:
        raise HTTPException(status_code=404, detail="Application not found")
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
    item = await db.get(models.Application, application_id)
    if not item:
        raise HTTPException(status_code=404, detail="Application not found")
    values = [
        {"code": "BUSINESS_INFO", "complete": bool(item.industry and item.state)},
        {"code": "OWNERS", "complete": False},
        {"code": "BANK_CONNECTION", "complete": False},
        {"code": "DOCUMENTS", "complete": False},
        {"code": "CONSENTS", "complete": True},
    ]
    complete = sum(1 for value in values if value["complete"])
    return {
        "completion_percentage": int(complete / len(values) * 100),
        "requirements": values,
        "next_action": next((v["code"] for v in values if not v["complete"]), "SUBMIT"),
    }


@router.post(
    "/applications/{application_id}/match",
    response_model=list[schemas.MatchRead],
    tags=["matching"],
)
async def match_application(application_id: uuid.UUID, db: Db, user: User):
    return await services.match(db, application_id)


@router.get(
    "/applications/{application_id}/matches",
    response_model=list[schemas.MatchRead],
    tags=["matching"],
)
async def matches(application_id: uuid.UUID, db: Db, user: User):
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
    if offer.status != "AVAILABLE":
        raise HTTPException(status_code=409, detail="Offer is not available")
    offer.status = "ACCEPTED"
    offer.version += 1
    application = await db.get(models.Application, offer.application_id)
    if application:
        application.status = models.ApplicationStatus.OFFER_ACCEPTED
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
