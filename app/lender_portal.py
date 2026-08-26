from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.auth import Principal, get_current_user
from app.db import get_db
from app.lender_portal_models import LenderPortalDecision
from app.portal_models import PortalTask
from app.portal_permissions import (
    has_permission,
    require_active_organization,
    require_any_permission,
)

router = APIRouter(prefix="/lender", tags=["lender-bank-portal"])


class LenderProgramPatch(BaseModel):
    active: bool | None = None
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    min_term_months: int | None = Field(default=None, ge=1, le=360)
    max_term_months: int | None = Field(default=None, ge=1, le=360)
    min_credit_score: int | None = Field(default=None, ge=300, le=850)
    min_monthly_revenue: Decimal | None = Field(default=None, ge=0)
    industries: list[str] | None = None
    states: list[str] | None = None


class LenderDecisionCreate(BaseModel):
    decision: Literal["APPROVE", "DECLINE", "REQUEST_INFORMATION"]
    reason_code: str | None = Field(default=None, max_length=100)
    comments: str | None = Field(default=None, max_length=10_000)
    approved_amount: Decimal | None = Field(default=None, gt=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    term_months: int | None = Field(default=None, ge=1, le=360)
    conditions: list[str] = Field(default_factory=list, max_length=100)


class LenderDecisionRead(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    decision: str
    reason_code: str | None
    comments: str | None
    status: str
    created_at: datetime
    replayed: bool = False


def _json_value(value: Any) -> Any:
    if isinstance(value, (uuid.UUID, datetime, date, Decimal)):
        return str(value)
    return value


def _record(source: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: _json_value(getattr(source, field, None))
        for field in fields
        if hasattr(source, field)
    }


def _require_lender(principal: Principal) -> uuid.UUID:
    if principal.lender_id is None or "LENDER" not in principal.membership_types:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "LENDER_CONTEXT_REQUIRED",
                "message": "An active lender membership is required.",
            },
        )
    require_active_organization(principal)
    return principal.lender_id


def _submission(
    db: Session,
    principal: Principal,
    submission_id: uuid.UUID,
):
    lender_id = _require_lender(principal)
    submission = db.scalar(
        select(models.LenderSubmission).where(
            models.LenderSubmission.id == submission_id,
            models.LenderSubmission.lender_id == lender_id,
        )
    )
    if submission is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Submission was not found."},
        )
    return submission


def _canonical_request_hash(payload: LenderDecisionCreate) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _program_read(program: Any) -> dict[str, Any]:
    return _record(
        program,
        (
            "id",
            "lender_id",
            "name",
            "product_type",
            "active",
            "min_amount",
            "max_amount",
            "min_term_months",
            "max_term_months",
            "min_credit_score",
            "min_monthly_revenue",
            "industries",
            "states",
            "created_at",
            "updated_at",
            "version",
        ),
    )


def _submission_read(submission: Any) -> dict[str, Any]:
    return _record(
        submission,
        (
            "id",
            "application_id",
            "lender_id",
            "program_id",
            "status",
            "provider_status",
            "submitted_at",
            "response_due_at",
            "decision_at",
            "created_at",
            "updated_at",
            "version",
        ),
    )


def _offer_read(offer: Any) -> dict[str, Any]:
    return _record(
        offer,
        (
            "id",
            "application_id",
            "lender_id",
            "status",
            "amount",
            "approved_amount",
            "interest_rate",
            "apr",
            "term_months",
            "monthly_payment",
            "origination_fee",
            "expires_at",
            "created_at",
            "updated_at",
            "version",
        ),
    )


@router.get("/workspace")
def lender_workspace(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=250),
):
    lender_id = _require_lender(principal)
    require_any_permission(principal, "lender.submission.read", "offer.create", "*")

    programs = list(
        db.scalars(
            select(models.LenderProgram)
            .where(models.LenderProgram.lender_id == lender_id)
            .order_by(models.LenderProgram.created_at.desc())
            .limit(limit)
        )
    )
    submissions = list(
        db.scalars(
            select(models.LenderSubmission)
            .where(models.LenderSubmission.lender_id == lender_id)
            .order_by(models.LenderSubmission.created_at.desc())
            .limit(limit)
        )
    )
    application_ids = [item.application_id for item in submissions]
    offers = []
    if application_ids:
        offers = list(
            db.scalars(
                select(models.Offer)
                .where(
                    models.Offer.lender_id == lender_id,
                    models.Offer.application_id.in_(application_ids),
                )
                .order_by(models.Offer.created_at.desc())
                .limit(limit)
            )
        )

    pending_statuses = {
        "QUEUED",
        "SUBMITTED",
        "UNDER_REVIEW",
        "REQUESTED_INFORMATION",
        "PENDING",
    }
    return {
        "principal": {
            "user_id": str(principal.user_id),
            "lender_id": str(lender_id),
            "organization_id": str(require_active_organization(principal)),
        },
        "summary": {
            "program_count": len(programs),
            "active_program_count": sum(
                1 for program in programs if bool(getattr(program, "active", False))
            ),
            "submission_count": len(submissions),
            "pending_submission_count": sum(
                1
                for submission in submissions
                if str(getattr(submission, "status", "")).upper() in pending_statuses
            ),
            "offer_count": len(offers),
        },
        "programs": [_program_read(item) for item in programs],
        "submissions": [_submission_read(item) for item in submissions],
        "offers": [_offer_read(item) for item in offers],
    }


@router.get("/programs")
def list_lender_programs(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    lender_id = _require_lender(principal)
    require_any_permission(principal, "lender.submission.read", "program.manage", "*")
    programs = db.scalars(
        select(models.LenderProgram)
        .where(models.LenderProgram.lender_id == lender_id)
        .order_by(models.LenderProgram.created_at.desc())
    )
    return {"items": [_program_read(item) for item in programs]}


@router.patch("/programs/{program_id}")
def patch_lender_program(
    program_id: uuid.UUID,
    payload: LenderProgramPatch,
    expected_version: Annotated[str, Header(alias="If-Match")],
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    lender_id = _require_lender(principal)
    require_any_permission(principal, "program.manage", "*")
    try:
        version = int(expected_version.strip('W/"'))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_IF_MATCH", "message": "If-Match must be a version."},
        ) from exc

    program = db.scalar(
        select(models.LenderProgram).where(
            models.LenderProgram.id == program_id,
            models.LenderProgram.lender_id == lender_id,
        )
    )
    if program is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Program was not found."},
        )
    current_version = int(getattr(program, "version", 1))
    if current_version != version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VERSION_CONFLICT",
                "message": "The program changed after it was loaded.",
                "context": {"current_version": current_version},
            },
        )

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return _program_read(program)
    for field, value in changes.items():
        if hasattr(program, field):
            setattr(program, field, value)
    if hasattr(program, "version"):
        program.version = current_version + 1
    db.commit()
    db.refresh(program)
    return _program_read(program)


@router.get("/submissions/{submission_id}/workspace")
def lender_submission_workspace(
    submission_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    require_any_permission(principal, "lender.submission.read", "offer.create", "*")
    submission = _submission(db, principal, submission_id)
    offers = list(
        db.scalars(
            select(models.Offer)
            .where(
                models.Offer.application_id == submission.application_id,
                models.Offer.lender_id == submission.lender_id,
            )
            .order_by(models.Offer.created_at.desc())
        )
    )
    decisions = list(
        db.scalars(
            select(LenderPortalDecision)
            .where(LenderPortalDecision.submission_id == submission.id)
            .order_by(LenderPortalDecision.created_at.desc())
        )
    )
    tasks = list(
        db.scalars(
            select(PortalTask)
            .where(
                PortalTask.organization_id == require_active_organization(principal),
                PortalTask.application_id == submission.application_id,
            )
            .order_by(PortalTask.created_at.desc())
        )
    )
    return {
        "submission": _submission_read(submission),
        "offers": [_offer_read(item) for item in offers],
        "decisions": [
            _record(
                item,
                (
                    "id",
                    "decision",
                    "reason_code",
                    "comments",
                    "status",
                    "created_at",
                ),
            )
            for item in decisions
        ],
        "tasks": [
            _record(
                item,
                (
                    "id",
                    "task_type",
                    "title",
                    "status",
                    "priority",
                    "due_at",
                    "version",
                    "created_at",
                ),
            )
            for item in tasks
        ],
    }


@router.post(
    "/submissions/{submission_id}/decisions",
    response_model=LenderDecisionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def record_lender_decision(
    submission_id: uuid.UUID,
    payload: LenderDecisionCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    lender_id = _require_lender(principal)
    require_any_permission(principal, "offer.create", "lender.decision.create", "*")
    submission = _submission(db, principal, submission_id)
    request_hash = _canonical_request_hash(payload)

    existing = db.scalar(
        select(LenderPortalDecision).where(
            LenderPortalDecision.lender_id == lender_id,
            LenderPortalDecision.submission_id == submission_id,
            LenderPortalDecision.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": "The idempotency key was already used with different data.",
                },
            )
        return LenderDecisionRead(
            id=existing.id,
            submission_id=existing.submission_id,
            decision=existing.decision,
            reason_code=existing.reason_code,
            comments=existing.comments,
            status=existing.status,
            created_at=existing.created_at,
            replayed=True,
        )

    decision = LenderPortalDecision(
        organization_id=require_active_organization(principal),
        lender_id=lender_id,
        submission_id=submission_id,
        created_by_user_id=principal.user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        decision=payload.decision,
        reason_code=payload.reason_code,
        comments=payload.comments,
        decision_payload=payload.model_dump(mode="json", exclude_none=True),
        status="PENDING_REVIEW",
    )
    task = PortalTask(
        organization_id=require_active_organization(principal),
        application_id=submission.application_id,
        created_by_user_id=principal.user_id,
        task_type="LENDER_DECISION_REVIEW",
        title=f"Review lender decision: {payload.decision}",
        description=payload.comments,
        status="OPEN",
        priority="HIGH" if payload.decision == "APPROVE" else "NORMAL",
        metadata_payload={
            "submission_id": str(submission_id),
            "lender_id": str(lender_id),
            "decision_id": str(decision.id),
        },
    )
    db.add_all([decision, task])
    db.commit()
    db.refresh(decision)
    return LenderDecisionRead(
        id=decision.id,
        submission_id=decision.submission_id,
        decision=decision.decision,
        reason_code=decision.reason_code,
        comments=decision.comments,
        status=decision.status,
        created_at=decision.created_at,
        replayed=False,
    )


@router.get("/bank-analysis-queue")
def bank_analysis_queue(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=250),
):
    lender_id = _require_lender(principal)
    require_any_permission(principal, "lender.submission.read", "underwriting.review", "*")
    submission_application_ids = list(
        db.scalars(
            select(models.LenderSubmission.application_id).where(
                models.LenderSubmission.lender_id == lender_id
            )
        )
    )
    if not submission_application_ids:
        return {"items": [], "count": 0}
    analyses = list(
        db.scalars(
            select(models.BankAnalysis)
            .where(models.BankAnalysis.application_id.in_(submission_application_ids))
            .order_by(models.BankAnalysis.created_at.desc())
            .limit(limit)
        )
    )
    return {
        "items": [
            _record(
                item,
                (
                    "id",
                    "application_id",
                    "status",
                    "average_monthly_revenue",
                    "average_daily_balance",
                    "negative_day_count",
                    "nsf_count",
                    "deposit_count",
                    "analysis_period_start",
                    "analysis_period_end",
                    "created_at",
                    "updated_at",
                    "version",
                ),
            )
            for item in analyses
        ],
        "count": len(analyses),
    }


@router.get("/portfolio")
def lender_portfolio(
    principal: Annotated[Principal, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    lender_id = _require_lender(principal)
    require_any_permission(principal, "lender.submission.read", "*")
    submission_rows = db.execute(
        select(models.LenderSubmission.status, func.count(models.LenderSubmission.id))
        .where(models.LenderSubmission.lender_id == lender_id)
        .group_by(models.LenderSubmission.status)
    ).all()
    offer_rows = db.execute(
        select(models.Offer.status, func.count(models.Offer.id))
        .where(models.Offer.lender_id == lender_id)
        .group_by(models.Offer.status)
    ).all()
    return {
        "submission_status_counts": {
            str(state): int(count) for state, count in submission_rows
        },
        "offer_status_counts": {str(state): int(count) for state, count in offer_rows},
        "can_manage_programs": has_permission(principal, "program.manage", "*"),
        "can_create_decisions": has_permission(
            principal, "offer.create", "lender.decision.create", "*"
        ),
    }
