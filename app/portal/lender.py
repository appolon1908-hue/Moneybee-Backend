from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.auth import Principal, current_principal
from app.db import get_db
from app.portal.common import problem, require_any_permission
from app.portal.schemas import (
    BankTransactionRead,
    LenderDashboard,
    LenderDecisionInput,
    LenderDecisionRead,
    LenderProgramUpdate,
    LenderWorkspace,
)


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


def _scope(user: Principal) -> uuid.UUID | None:
    if "*" in user.permissions:
        return user.lender_id
    if user.lender_id is None:
        problem(
            "RESOURCE_ACCESS_DENIED",
            "An active lender organization membership is required.",
            403,
        )
    return user.lender_id


def _submission_payload(item: models.LenderSubmission) -> dict:
    return {
        "id": str(item.id),
        "application_id": str(item.application_id),
        "lender_id": str(item.lender_id),
        "program_id": str(item.program_id),
        "program_version": item.program_version,
        "external_submission_id": item.external_submission_id,
        "status": item.status,
        "version": item.version,
        "submitted_at": item.submitted_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _application_payload(item: models.Application) -> dict:
    return {
        "id": str(item.id),
        "requested_amount": str(item.requested_amount),
        "monthly_revenue": str(item.monthly_revenue),
        "time_in_business_months": item.time_in_business_months,
        "industry": item.industry,
        "state": item.state,
        "status": item.status,
        "completion_percentage": item.completion_percentage,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def _authorized_submission(
    db: AsyncSession,
    submission_id: uuid.UUID,
    user: Principal,
    *,
    lock: bool = False,
) -> models.LenderSubmission:
    statement = select(models.LenderSubmission).where(
        models.LenderSubmission.id == submission_id
    )
    if lock:
        statement = statement.with_for_update()
    item = await db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    lender_id = _scope(user)
    if lender_id and item.lender_id != lender_id:
        problem(
            "RESOURCE_ACCESS_DENIED",
            "The submission is outside the active lender organization.",
            403,
        )
    return item


async def _authorized_program(
    db: AsyncSession,
    program_id: uuid.UUID,
    user: Principal,
    *,
    lock: bool = False,
) -> models.LenderProgram:
    statement = select(models.LenderProgram).where(models.LenderProgram.id == program_id)
    if lock:
        statement = statement.with_for_update()
    item = await db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Lender program not found")
    lender_id = _scope(user)
    if lender_id and item.lender_id != lender_id:
        problem(
            "RESOURCE_ACCESS_DENIED",
            "The program is outside the active lender organization.",
            403,
        )
    return item


@router.get(
    "/lender/dashboard",
    response_model=LenderDashboard,
    tags=["lender", "portal"],
)
async def lender_dashboard(db: Db, user: User):
    require_any_permission(user, "lender.application.read", "lender.submission.read")
    lender_id = _scope(user)

    def scoped_count(model, *criteria):
        statement = select(func.count(model.id)).where(*criteria)
        if lender_id:
            statement = statement.where(model.lender_id == lender_id)
        return statement

    programs = await db.scalar(scoped_count(models.LenderProgram)) or 0
    active_programs = (
        await db.scalar(scoped_count(models.LenderProgram, models.LenderProgram.active.is_(True)))
        or 0
    )
    submissions = await db.scalar(scoped_count(models.LenderSubmission)) or 0
    needs_review = (
        await db.scalar(
            scoped_count(
                models.LenderSubmission,
                models.LenderSubmission.status.in_(["DRAFT", "QUEUED", "SUBMITTED", "UNDER_REVIEW"]),
            )
        )
        or 0
    )
    conditions_pending = (
        await db.scalar(
            scoped_count(
                models.LenderSubmission,
                models.LenderSubmission.status == "CONDITIONS",
            )
        )
        or 0
    )
    offers_out = await db.scalar(scoped_count(models.Offer, models.Offer.status == "AVAILABLE")) or 0

    funding_statement = (
        select(func.count(models.Funding.id), func.coalesce(func.sum(models.Funding.funded_amount), 0))
        .join(models.Offer, models.Offer.id == models.Funding.offer_id)
        .where(models.Funding.status.in_(["FUNDS_SENT", "FUNDED", "CLOSED"]))
    )
    if lender_id:
        funding_statement = funding_statement.where(models.Offer.lender_id == lender_id)
    funding_row = (await db.execute(funding_statement)).one()
    return LenderDashboard(
        lender_id=lender_id,
        programs=programs,
        active_programs=active_programs,
        submissions=submissions,
        needs_review=needs_review,
        conditions_pending=conditions_pending,
        offers_out=offers_out,
        funded_deals=int(funding_row[0] or 0),
        total_funded=str(funding_row[1] or Decimal("0")),
    )


@router.get(
    "/lender/programs",
    response_model=list[dict],
    tags=["lender", "programs"],
)
async def lender_programs(
    db: Db,
    user: User,
    include_inactive: bool = False,
):
    require_any_permission(user, "program.manage", "lender.application.read")
    lender_id = _scope(user)
    statement = select(models.LenderProgram)
    if lender_id:
        statement = statement.where(models.LenderProgram.lender_id == lender_id)
    if not include_inactive:
        statement = statement.where(models.LenderProgram.active.is_(True))
    rows = list(
        (
            await db.scalars(
                statement.order_by(models.LenderProgram.name, models.LenderProgram.version.desc())
            )
        ).all()
    )
    return [
        {
            "id": str(row.id),
            "lender_id": str(row.lender_id),
            "name": row.name,
            "product_type": row.product_type,
            "min_amount": str(row.min_amount),
            "max_amount": str(row.max_amount),
            "minimum_monthly_revenue": str(row.minimum_monthly_revenue),
            "minimum_time_in_business_months": row.minimum_time_in_business_months,
            "states": row.states,
            "excluded_industries": row.excluded_industries,
            "active": row.active,
            "version": row.version,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.patch(
    "/lender/programs/{program_id}",
    response_model=dict,
    tags=["lender", "programs"],
)
async def update_lender_program(
    program_id: uuid.UUID,
    payload: LenderProgramUpdate,
    db: Db,
    user: User,
):
    require_any_permission(user, "program.manage")
    item = await _authorized_program(db, program_id, user, lock=True)
    if item.version != payload.version:
        problem(
            "CONCURRENT_MODIFICATION",
            f"Program version {payload.version} is stale; current version is {item.version}.",
            409,
        )
    values = payload.model_dump(exclude={"version"}, exclude_none=True)
    if "min_amount" in values and "max_amount" in values and values["min_amount"] > values["max_amount"]:
        problem("INVALID_PROGRAM_RANGE", "Minimum amount cannot exceed maximum amount.", 422)
    for name, value in values.items():
        setattr(item, name, value)
    if item.min_amount > item.max_amount:
        problem("INVALID_PROGRAM_RANGE", "Minimum amount cannot exceed maximum amount.", 422)
    item.version += 1
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="LENDER_PROGRAM_UPDATED",
            resource_type="lender_program",
            resource_id=str(item.id),
            details={"version": item.version, "fields": sorted(values)},
        )
    )
    await db.commit()
    await db.refresh(item)
    return {
        "id": str(item.id),
        "lender_id": str(item.lender_id),
        "name": item.name,
        "product_type": item.product_type,
        "min_amount": str(item.min_amount),
        "max_amount": str(item.max_amount),
        "minimum_monthly_revenue": str(item.minimum_monthly_revenue),
        "minimum_time_in_business_months": item.minimum_time_in_business_months,
        "states": item.states,
        "excluded_industries": item.excluded_industries,
        "active": item.active,
        "version": item.version,
        "updated_at": item.updated_at,
    }


@router.get(
    "/lender/submissions/{submission_id}/workspace",
    response_model=LenderWorkspace,
    tags=["lender", "portal"],
)
async def lender_submission_workspace(submission_id: uuid.UUID, db: Db, user: User):
    require_any_permission(user, "lender.application.read", "lender.submission.read")
    submission = await _authorized_submission(db, submission_id, user)
    application = await db.get(models.Application, submission.application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    business = await db.scalar(
        select(models.Business).where(models.Business.application_id == application.id)
    )
    financial = await db.scalar(
        select(models.FinancialProfile).where(models.FinancialProfile.application_id == application.id)
    )
    analysis = await db.scalar(
        select(models.BankAnalysis)
        .where(models.BankAnalysis.application_id == application.id)
        .order_by(models.BankAnalysis.created_at.desc())
    )
    conditions = list(
        (
            await db.scalars(
                select(models.UnderwritingCondition)
                .where(models.UnderwritingCondition.submission_id == submission.id)
                .order_by(models.UnderwritingCondition.created_at.desc())
            )
        ).all()
    )
    offers = list(
        (
            await db.scalars(
                select(models.Offer)
                .where(
                    models.Offer.application_id == application.id,
                    models.Offer.lender_id == submission.lender_id,
                )
                .order_by(models.Offer.created_at.desc())
            )
        ).all()
    )
    documents = list(
        (
            await db.scalars(
                select(models.Document)
                .where(
                    models.Document.application_id == application.id,
                    models.Document.status.in_(["CLEAN", "APPROVED"]),
                )
                .order_by(models.Document.created_at.desc())
            )
        ).all()
    )
    return LenderWorkspace(
        submission=_submission_payload(submission),
        application=_application_payload(application),
        business=(
            {
                "legal_name": business.legal_name,
                "dba": business.dba,
                "entity_type": business.entity_type,
                "state_formed": business.state_formed,
                "industry": business.industry,
                "naics": business.naics,
            }
            if business
            else None
        ),
        financial_profile=(
            {
                "annual_revenue": str(financial.annual_revenue) if financial.annual_revenue is not None else None,
                "monthly_revenue": str(financial.monthly_revenue) if financial.monthly_revenue is not None else None,
                "monthly_expenses": str(financial.monthly_expenses) if financial.monthly_expenses is not None else None,
                "existing_debt": str(financial.existing_debt) if financial.existing_debt is not None else None,
                "existing_positions": financial.existing_positions,
            }
            if financial
            else None
        ),
        bank_analysis=(
            {
                "id": str(analysis.id),
                "average_monthly_deposits": str(analysis.average_monthly_deposits) if analysis.average_monthly_deposits is not None else None,
                "average_daily_balance": str(analysis.average_daily_balance) if analysis.average_daily_balance is not None else None,
                "negative_balance_days_90d": analysis.negative_balance_days_90d,
                "nsf_count_90d": analysis.nsf_count_90d,
                "deposit_count_90d": analysis.deposit_count_90d,
                "largest_deposit_90d": str(analysis.largest_deposit_90d) if analysis.largest_deposit_90d is not None else None,
                "revenue_trend": analysis.revenue_trend,
                "cash_flow_trend": analysis.cash_flow_trend,
                "risk_flags": analysis.risk_flags,
                "created_at": analysis.created_at,
            }
            if analysis
            else None
        ),
        conditions=[
            {
                "id": str(row.id),
                "description": row.description,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in conditions
        ],
        offers=[
            {
                "id": str(row.id),
                "amount": str(row.amount),
                "term_months": row.term_months,
                "payment_frequency": row.payment_frequency,
                "payment_amount": str(row.payment_amount),
                "apr": str(row.apr) if row.apr is not None else None,
                "factor_rate": str(row.factor_rate) if row.factor_rate is not None else None,
                "status": row.status,
                "expires_at": row.expires_at,
                "version": row.version,
            }
            for row in offers
        ],
        documents=[
            {
                "id": str(row.id),
                "document_type": row.document_type,
                "file_name": row.original_file_name,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in documents
        ],
    )


@router.get(
    "/lender/bank-review-queue",
    response_model=list[dict],
    tags=["lender", "banking"],
)
async def lender_bank_review_queue(db: Db, user: User):
    require_any_permission(user, "lender.bank.read", "lender.submission.read")
    lender_id = _scope(user)
    statement = (
        select(models.LenderSubmission, models.Application, models.BankAnalysis)
        .join(models.Application, models.Application.id == models.LenderSubmission.application_id)
        .outerjoin(models.BankAnalysis, models.BankAnalysis.application_id == models.Application.id)
        .where(models.LenderSubmission.status.in_(["DRAFT", "SUBMITTED", "UNDER_REVIEW", "CONDITIONS"]))
        .order_by(models.LenderSubmission.created_at)
        .limit(200)
    )
    if lender_id:
        statement = statement.where(models.LenderSubmission.lender_id == lender_id)
    rows = (await db.execute(statement)).all()
    return [
        {
            "submission_id": str(submission.id),
            "application_id": str(application.id),
            "status": submission.status,
            "version": submission.version,
            "requested_amount": str(application.requested_amount),
            "monthly_revenue": str(application.monthly_revenue),
            "analysis_available": analysis is not None,
            "average_monthly_deposits": (
                str(analysis.average_monthly_deposits)
                if analysis and analysis.average_monthly_deposits is not None
                else None
            ),
            "nsf_count_90d": analysis.nsf_count_90d if analysis else None,
            "risk_flags": analysis.risk_flags if analysis else [],
            "submitted_at": submission.submitted_at,
            "created_at": submission.created_at,
        }
        for submission, application, analysis in rows
    ]


@router.get(
    "/lender/submissions/{submission_id}/bank-transactions",
    response_model=list[BankTransactionRead],
    tags=["lender", "banking"],
)
async def lender_bank_transactions(
    submission_id: uuid.UUID,
    db: Db,
    user: User,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
):
    require_any_permission(user, "lender.bank.read")
    submission = await _authorized_submission(db, submission_id, user)
    return list(
        (
            await db.scalars(
                select(models.BankTransaction)
                .join(
                    models.BankConnection,
                    models.BankConnection.id == models.BankTransaction.connection_id,
                )
                .where(models.BankConnection.application_id == submission.application_id)
                .order_by(models.BankTransaction.posted_at.desc())
                .limit(limit)
            )
        ).all()
    )


@router.post(
    "/lender/submissions/{submission_id}/decisions",
    response_model=LenderDecisionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["lender", "underwriting"],
)
async def lender_decision(
    submission_id: uuid.UUID,
    payload: LenderDecisionInput,
    db: Db,
    user: User,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=160)],
):
    require_any_permission(user, "lender.decision.create", "underwriting.review")
    submission = await _authorized_submission(db, submission_id, user, lock=True)
    if submission.version != payload.expected_version:
        problem(
            "CONCURRENT_MODIFICATION",
            f"Submission version {payload.expected_version} is stale; current version is {submission.version}.",
            409,
        )
    route = f"/lender/submissions/{submission_id}/decisions"
    request_hash = hashlib.sha256(
        json.dumps(
            payload.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    existing = await db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_id == user.subject,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            problem(
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key was already used with a different decision.",
                409,
            )
        return LenderDecisionRead.model_validate(existing.response_body)
    status_by_decision = {
        "APPROVE": "APPROVED",
        "DECLINE": "DECLINED",
        "CONDITIONS": "CONDITIONS",
        "FRAUD_REVIEW": "ESCALATED",
        "COMPLIANCE_REVIEW": "ESCALATED",
    }
    submission.status = status_by_decision[payload.decision]
    submission.version += 1
    review = models.UnderwritingReview(
        application_id=submission.application_id,
        submission_id=submission.id,
        reviewer_subject=user.subject,
        decision=payload.decision,
        reason_codes=payload.reason_codes,
        notes=payload.notes,
        policy_version=1,
    )
    db.add(review)
    await db.flush()
    db.add(
        models.AuditEvent(
            actor_id=user.subject,
            action="LENDER_SUBMISSION_DECIDED",
            resource_type="lender_submission",
            resource_id=str(submission.id),
            details={
                "decision": payload.decision,
                "reason_codes": payload.reason_codes,
                "version": submission.version,
            },
        )
    )
    db.add(
        models.OutboxEvent(
            event_type="LenderDecisionRecorded",
            aggregate_type="lender_submission",
            aggregate_id=submission.id,
            aggregate_version=submission.version,
            tenant_id=str(submission.lender_id),
            payload={
                "submission_id": str(submission.id),
                "application_id": str(submission.application_id),
                "lender_id": str(submission.lender_id),
                "decision": payload.decision,
                "reason_codes": payload.reason_codes,
            },
            idempotency_key=f"LenderDecisionRecorded:{submission.id}:{submission.version}",
        )
    )
    response = LenderDecisionRead(
        review_id=review.id,
        submission_id=submission.id,
        application_id=submission.application_id,
        decision=review.decision,
        status=submission.status,
        version=submission.version,
        created_at=review.created_at,
    )
    db.add(
        models.IdempotencyRecord(
            key=idempotency_key,
            actor_id=user.subject,
            route=route,
            request_hash=request_hash,
            response_status=201,
            response_body=response.model_dump(mode="json"),
        )
    )
    await db.commit()
    return response


@router.get(
    "/lender/fundings",
    response_model=list[dict],
    tags=["lender", "funding"],
)
async def lender_fundings(db: Db, user: User):
    require_any_permission(user, "lender.application.read", "lender.submission.read")
    lender_id = _scope(user)
    statement = (
        select(models.Funding, models.Offer)
        .join(models.Offer, models.Offer.id == models.Funding.offer_id)
        .order_by(models.Funding.created_at.desc())
        .limit(500)
    )
    if lender_id:
        statement = statement.where(models.Offer.lender_id == lender_id)
    rows = (await db.execute(statement)).all()
    return [
        {
            "id": str(funding.id),
            "application_id": str(funding.application_id),
            "offer_id": str(funding.offer_id),
            "status": funding.status,
            "approved_amount": str(funding.approved_amount) if funding.approved_amount is not None else None,
            "funded_amount": str(funding.funded_amount) if funding.funded_amount is not None else None,
            "provider_reference": funding.provider_reference,
            "product_type": offer.product_type,
            "created_at": funding.created_at,
            "funding_confirmed_at": funding.funding_confirmed_at,
        }
        for funding, offer in rows
    ]
