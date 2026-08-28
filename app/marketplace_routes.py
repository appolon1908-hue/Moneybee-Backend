import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas, services
from app.auth import Principal, current_principal, require_permission
from app.db import get_db


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


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
    if "*" not in user.permissions and user.lender_id != lender_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "RESOURCE_ACCESS_DENIED",
                "message": "The lender organization does not own this resource.",
            },
        )
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
    if "*" not in user.permissions and user.lender_id != payload.lender_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "RESOURCE_ACCESS_DENIED",
                "message": "The lender organization does not own this resource.",
            },
        )
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


def lender_scope(user: Principal) -> uuid.UUID | None:
    if "*" in user.permissions:
        return None
    if user.lender_id is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "RESOURCE_ACCESS_DENIED",
                "message": "An active lender membership is required.",
            },
        )
    return user.lender_id


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
                models.LenderSubmission.program_version == match.program_version,
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
    user: Annotated[Principal, Depends(require_permission("lender.submission.read"))],
):
    lender_id = lender_scope(user)
    statement = select(models.LenderSubmission)
    if lender_id:
        statement = statement.where(models.LenderSubmission.lender_id == lender_id)
    return list(
        (await db.scalars(statement.order_by(models.LenderSubmission.created_at.desc()))).all()
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
        raise HTTPException(
            status_code=403,
            detail={
                "code": "RESOURCE_ACCESS_DENIED",
                "message": "The lender organization does not own this submission.",
            },
        )
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
    user: Annotated[Principal, Depends(require_permission("lender.condition.create"))],
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
    await services.get_authorized_application(db, item.application_id, user, write=True)
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
    user: Annotated[Principal, Depends(require_permission("lender.condition.review"))],
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
    user: Annotated[Principal, Depends(require_permission("lender.condition.review"))],
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
    user: Annotated[Principal, Depends(require_permission("lender.condition.review"))],
):
    return await decide_condition(condition_id, "WAIVED", db, user)
