import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import domain_logic, models, schemas, services
from app.auth import Principal, current_principal, require_permission
from app.commands import AcceptOfferCommand, command_context, parse_expected_version
from app.config import settings
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


@router.get(
    "/me",
    response_model=schemas.PrincipalRead,
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Authentication or binding failed"},
        403: {
            "model": schemas.ErrorResponse,
            "description": "User, membership, or tenant rejected",
        },
    },
    tags=["identity"],
)
async def me(user: User):
    return schemas.PrincipalRead(
        user_id=user.user_id,
        issuer=user.issuer,
        subject=user.subject,
        organization_ids=list(user.organization_ids),
        active_organization_id=user.active_organization_id,
        roles=sorted(user.roles),
        permissions=sorted(user.permissions),
        membership_types=sorted(user.membership_types),
        borrower_id=user.borrower_id,
        lender_id=user.lender_id,
        is_active=user.is_active,
    )


@router.get("/me/capabilities", tags=["identity"])
async def my_capabilities(db: Db, user: User):
    return await services.effective_capabilities(db)


@router.post("/applications", response_model=schemas.ApplicationRead, tags=["applications"])
async def create_application(payload: schemas.ApplicationCreate, db: Db, user: User):
    existing = await db.scalar(
        select(models.Application).where(models.Application.lead_id == payload.lead_id)
    )
    if existing:
        if "BORROWER" in user.membership_types and not existing.borrower_subject:
            existing.borrower_subject = user.subject
            existing.borrower_organization_id = user.borrower_id
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
        borrower_subject=(user.subject if "BORROWER" in user.membership_types else None),
        borrower_organization_id=user.borrower_id,
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
    item = await services.get_authorized_application(db, application_id, user, write=True)
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
    request: Request,
    db: Db,
    user: User,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=160)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    command = AcceptOfferCommand(
        offer_id=offer_id,
        expected_application_version=parse_expected_version(if_match),
    )
    context = command_context(
        request,
        user,
        idempotency_key=idempotency_key,
    )
    if settings.app_env == "production" and command.expected_application_version is None:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "EXPECTED_VERSION_REQUIRED",
                "message": "If-Match is required for offer acceptance.",
            },
        )
    route = f"/offers/{offer_id}/accept"
    request_hash = hashlib.sha256(
        f"{offer_id}:{command.expected_application_version}".encode()
    ).hexdigest()
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
        replay_offer = await db.get(models.Offer, uuid.UUID(replay.response_body["offer_id"]))
        if replay_offer is None:
            raise HTTPException(status_code=409, detail="Stored replay target is unavailable")
        return replay_offer

    offer = await db.scalar(
        select(models.Offer).where(models.Offer.id == command.offer_id).with_for_update()
    )
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    application = await db.scalar(
        select(models.Application)
        .where(models.Application.id == offer.application_id)
        .with_for_update()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    services.authorize_application(application, user, write=True)
    if (
        command.expected_application_version is not None
        and command.expected_application_version != application.version
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONCURRENT_MODIFICATION",
                "expected_version": command.expected_application_version,
                "actual_version": application.version,
            },
        )
    if "*" not in user.permissions and "offer.accept.own" not in user.permissions:
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
        select(models.Funding).where(models.Funding.application_id == application.id)
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
    await db.flush()
    submission_id_for_offer = await db.scalar(
        select(models.LenderSubmission.id).where(
            models.LenderSubmission.application_id == application.id,
            models.LenderSubmission.lender_id == offer.lender_id,
            models.LenderSubmission.program_id == offer.program_id,
        )
    )
    if submission_id_for_offer is not None:
        await services.advance_funding_if_conditions_satisfied(
            db, submission_id_for_offer, user
        )
    db.add(
        models.OutboxEvent(
            event_type="offer.accepted.v1",
            aggregate_type="application",
            aggregate_id=application.id,
            aggregate_version=application.version,
            tenant_id=context.tenant_id,
            correlation_id=context.correlation_id,
            causation_id=context.request_id,
            payload={
                "offer_id": str(offer.id),
                "lender_id": str(offer.lender_id),
                "amount": str(offer.amount),
            },
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
    item = await services.get_authorized_application(db, application_id, user, write=True)
    if "*" not in user.permissions and "application.submit.own" not in user.permissions:
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
    if "*" not in user.permissions and "credit.authorize.own" not in user.permissions:
        raise HTTPException(status_code=403, detail="Permission denied")
    existing = await db.scalar(
        select(models.CreditAuthorization).where(
            models.CreditAuthorization.application_id == application_id,
            models.CreditAuthorization.authorization_version == payload.authorization_version,
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
                .where(models.UnderwritingCondition.application_id == application_id)
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
    if "*" not in user.permissions and "complaint.create.own" not in user.permissions:
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
    "/applications/{application_id}/contract",
    response_model=schemas.ContractRead | None,
    tags=["funding"],
)
async def application_contract(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return await db.scalar(
        select(models.Contract)
        .where(models.Contract.application_id == application_id)
        .order_by(models.Contract.created_at.desc())
    )


@router.get(
    "/applications/{application_id}/renewal-opportunities",
    response_model=list[schemas.RenewalRead],
    tags=["funding"],
)
async def application_renewal_opportunities(application_id: uuid.UUID, db: Db, user: User):
    await services.get_authorized_application(db, application_id, user)
    return list(
        (
            await db.scalars(
                select(models.RenewalOpportunity)
                .where(models.RenewalOpportunity.application_id == application_id)
                .order_by(models.RenewalOpportunity.created_at.desc())
            )
        ).all()
    )


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
    "/applications/{application_id}/requirement-snapshots",
    response_model=schemas.RequirementSnapshotRead,
    status_code=status.HTTP_201_CREATED,
    tags=["applications", "underwriting"],
)
async def create_requirement_snapshot(
    application_id: uuid.UUID,
    db: Db,
    user: Annotated[Principal, Depends(require_permission("underwriting.review"))],
):
    application = await services.get_authorized_application(db, application_id, user)
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
                .where(models.RequirementSnapshot.application_id == application_id)
                .order_by(models.RequirementSnapshot.created_at.desc())
            )
        ).all()
    )
