import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.auth import User, get_current_user
from app.db import get_db
from app.portal_models import PortalNotification, PortalTask
from app.portal_security import active_tenant, require_lender

router = APIRouter(prefix="/lender", tags=["lender-bank-portal"])


class LenderProgramPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=240)
    product_type: str | None = Field(default=None, min_length=2, max_length=80)
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    min_credit_score: int | None = Field(default=None, ge=300, le=850)
    min_monthly_revenue: Decimal | None = Field(default=None, ge=0)
    min_time_in_business_months: int | None = Field(default=None, ge=0)
    allowed_states: list[str] | None = Field(default=None, max_length=60)
    active: bool | None = None


class LenderDecisionCreate(BaseModel):
    decision: Literal["APPROVE", "DECLINE", "REQUEST_INFORMATION"]
    notes: str | None = Field(default=None, max_length=10_000)
    requested_items: list[str] = Field(default_factory=list, max_length=50)
    offer_amount: Decimal | None = Field(default=None, gt=0)
    term_months: int | None = Field(default=None, gt=0, le=120)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)


class AssignmentPatch(BaseModel):
    assigned_to_subject: str = Field(min_length=1, max_length=255)


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return value


def _public(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: _iso(getattr(row, field, None))
        for field in fields
        if hasattr(row, field)
    }


def _construct(model: type, values: dict[str, Any]) -> Any:
    columns = {column.name for column in model.__table__.columns}
    return model(**{key: value for key, value in values.items() if key in columns})


def _canonical_hash(payload: BaseModel) -> str:
    encoded = json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _expected_version(if_match: str | None) -> int:
    if not if_match:
        raise _problem(
            "PRECONDITION_REQUIRED",
            "If-Match with the current resource version is required.",
            428,
        )
    value = if_match.strip()
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    try:
        expected = int(value)
    except ValueError as exc:
        raise _problem(
            "INVALID_IF_MATCH",
            "If-Match must contain an integer resource version.",
            400,
        ) from exc
    if expected < 1:
        raise _problem(
            "INVALID_IF_MATCH",
            "If-Match must contain a positive resource version.",
            400,
        )
    return expected


async def _submission(
    *,
    submission_id: uuid.UUID,
    lender_id: uuid.UUID,
    db: AsyncSession,
    for_update: bool = False,
) -> models.LenderSubmission:
    query = select(models.LenderSubmission).where(
        models.LenderSubmission.id == submission_id,
        models.LenderSubmission.lender_id == lender_id,
    )
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    submission = result.scalar_one_or_none()
    if submission is None:
        raise _problem(
            "LENDER_SUBMISSION_NOT_FOUND",
            "Lender submission was not found.",
            404,
        )
    return submission


@router.get("/workspace")
async def lender_workspace(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    lender_id = require_lender(user.principal)
    programs = list(
        (
            await db.execute(
                select(models.LenderProgram)
                .where(models.LenderProgram.lender_id == lender_id)
                .order_by(models.LenderProgram.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    submissions = list(
        (
            await db.execute(
                select(models.LenderSubmission)
                .where(models.LenderSubmission.lender_id == lender_id)
                .order_by(models.LenderSubmission.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    task_result = await db.execute(
        select(PortalTask)
        .where(
            PortalTask.tenant_id == active_tenant(user.principal),
            PortalTask.assigned_to_subject == user.principal.subject,
            PortalTask.status.notin_(["COMPLETED", "CANCELLED"]),
        )
        .order_by(PortalTask.due_at.asc(), PortalTask.created_at.desc())
        .limit(50)
    )
    return {
        "summary": {
            "active_programs": sum(
                1 for program in programs if bool(getattr(program, "active", False))
            ),
            "submission_count": len(submissions),
            "pending_submissions": sum(
                1
                for submission in submissions
                if getattr(submission, "status", "")
                not in {"APPROVED", "DECLINED", "WITHDRAWN", "EXPIRED"}
            ),
        },
        "recent_submissions": [
            _public(
                submission,
                (
                    "id",
                    "application_id",
                    "program_id",
                    "status",
                    "assigned_to_subject",
                    "submitted_at",
                    "version",
                    "created_at",
                ),
            )
            for submission in submissions[:25]
        ],
        "open_tasks": [
            _public(
                task,
                (
                    "id",
                    "application_id",
                    "task_type",
                    "title",
                    "status",
                    "priority",
                    "due_at",
                    "version",
                ),
            )
            for task in task_result.scalars().all()
        ],
    }


@router.get("/programs")
async def list_lender_programs(
    active: bool | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    lender_id = require_lender(user.principal)
    query = select(models.LenderProgram).where(
        models.LenderProgram.lender_id == lender_id
    )
    if active is not None:
        query = query.where(models.LenderProgram.active == active)
    result = await db.execute(query.order_by(models.LenderProgram.created_at.desc()))
    return [
        _public(
            program,
            (
                "id",
                "lender_id",
                "name",
                "product_type",
                "min_amount",
                "max_amount",
                "min_credit_score",
                "min_monthly_revenue",
                "min_time_in_business_months",
                "allowed_states",
                "active",
                "version",
                "created_at",
                "updated_at",
            ),
        )
        for program in result.scalars().all()
    ]


@router.patch("/programs/{program_id}")
async def update_lender_program(
    program_id: uuid.UUID,
    payload: LenderProgramPatch,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    lender_id = require_lender(user.principal)
    expected_version = _expected_version(if_match)
    result = await db.execute(
        select(models.LenderProgram)
        .where(
            models.LenderProgram.id == program_id,
            models.LenderProgram.lender_id == lender_id,
        )
        .with_for_update()
    )
    program = result.scalar_one_or_none()
    if program is None:
        raise _problem("LENDER_PROGRAM_NOT_FOUND", "Lender program was not found.", 404)
    current_version = int(getattr(program, "version", 1))
    if current_version != expected_version:
        raise _problem(
            "RESOURCE_VERSION_CONFLICT",
            "The lender program changed after it was loaded.",
            409,
        )
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if hasattr(program, field):
            setattr(program, field, value)
    if hasattr(program, "version"):
        program.version = current_version + 1
    if (
        getattr(program, "min_amount", None) is not None
        and getattr(program, "max_amount", None) is not None
        and program.min_amount > program.max_amount
    ):
        raise _problem(
            "INVALID_PROGRAM_AMOUNT_RANGE",
            "Program minimum amount must not exceed maximum amount.",
            422,
        )
    db.add(
        _construct(
            models.AuditEvent,
            {
                "actor_subject": user.principal.subject,
                "action": "lender_program.updated",
                "entity_type": "lender_program",
                "entity_id": program.id,
                "details": {
                    "lender_id": str(lender_id),
                    "changed_fields": sorted(changes),
                    "expected_version": expected_version,
                    "new_version": getattr(program, "version", None),
                },
            },
        )
    )
    await db.commit()
    await db.refresh(program)
    return _public(
        program,
        (
            "id",
            "lender_id",
            "name",
            "product_type",
            "min_amount",
            "max_amount",
            "min_credit_score",
            "min_monthly_revenue",
            "min_time_in_business_months",
            "allowed_states",
            "active",
            "version",
            "updated_at",
        ),
    )


@router.get("/submissions/{submission_id}/workspace")
async def submission_workspace(
    submission_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    lender_id = require_lender(user.principal)
    submission = await _submission(
        submission_id=submission_id,
        lender_id=lender_id,
        db=db,
    )
    application = await db.get(models.Application, submission.application_id)
    if application is None:
        raise _problem("APPLICATION_NOT_FOUND", "Application was not found.", 404)
    conditions = list(
        (
            await db.execute(
                select(models.UnderwritingCondition)
                .where(
                    models.UnderwritingCondition.application_id == application.id
                )
                .order_by(models.UnderwritingCondition.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    analyses = list(
        (
            await db.execute(
                select(models.BankAnalysis)
                .where(models.BankAnalysis.application_id == application.id)
                .order_by(models.BankAnalysis.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    offers = list(
        (
            await db.execute(
                select(models.Offer)
                .where(
                    models.Offer.application_id == application.id,
                    models.Offer.lender_id == lender_id,
                )
                .order_by(models.Offer.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "submission": _public(
            submission,
            (
                "id",
                "application_id",
                "program_id",
                "status",
                "assigned_to_subject",
                "submitted_at",
                "external_reference",
                "version",
                "created_at",
                "updated_at",
            ),
        ),
        "application": _public(
            application,
            (
                "id",
                "status",
                "requested_amount",
                "use_of_funds",
                "version",
                "submitted_at",
                "created_at",
            ),
        ),
        "conditions": [
            _public(
                condition,
                (
                    "id",
                    "condition_type",
                    "title",
                    "description",
                    "status",
                    "due_at",
                    "satisfied_at",
                ),
            )
            for condition in conditions
        ],
        "bank_analyses": [
            _public(
                analysis,
                (
                    "id",
                    "status",
                    "analysis_type",
                    "average_monthly_revenue",
                    "average_daily_balance",
                    "negative_days",
                    "nsf_count",
                    "risk_flags",
                    "completed_at",
                    "created_at",
                ),
            )
            for analysis in analyses
        ],
        "offers": [
            _public(
                offer,
                (
                    "id",
                    "status",
                    "amount",
                    "term_months",
                    "interest_rate",
                    "factor_rate",
                    "payment_amount",
                    "payment_frequency",
                    "expires_at",
                ),
            )
            for offer in offers
        ],
    }


@router.patch("/submissions/{submission_id}/assignment")
async def assign_submission(
    submission_id: uuid.UUID,
    payload: AssignmentPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    lender_id = require_lender(user.principal)
    submission = await _submission(
        submission_id=submission_id,
        lender_id=lender_id,
        db=db,
        for_update=True,
    )
    if hasattr(submission, "assigned_to_subject"):
        submission.assigned_to_subject = payload.assigned_to_subject
    db.add(
        _construct(
            models.AuditEvent,
            {
                "actor_subject": user.principal.subject,
                "action": "lender_submission.assigned",
                "entity_type": "lender_submission",
                "entity_id": submission.id,
                "details": {
                    "lender_id": str(lender_id),
                    "assigned_to_subject": payload.assigned_to_subject,
                },
            },
        )
    )
    await db.commit()
    await db.refresh(submission)
    return _public(
        submission,
        ("id", "status", "assigned_to_subject", "version", "updated_at"),
    )


@router.post("/submissions/{submission_id}/decision")
async def record_lender_decision(
    submission_id: uuid.UUID,
    payload: LenderDecisionCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    principal = user.principal
    lender_id = require_lender(principal)
    if not idempotency_key or len(idempotency_key) > 255:
        raise _problem(
            "IDEMPOTENCY_KEY_REQUIRED",
            "A stable Idempotency-Key is required for lender decisions.",
            400,
        )
    route = f"POST:/api/v2/lender/submissions/{submission_id}/decision"
    request_hash = _canonical_hash(payload)
    existing_result = await db.execute(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.actor_subject == principal.subject,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.key == idempotency_key,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _problem(
                "IDEMPOTENCY_KEY_REUSED",
                "The Idempotency-Key was already used with a different decision.",
                409,
            )
        return existing.response_body
    submission = await _submission(
        submission_id=submission_id,
        lender_id=lender_id,
        db=db,
        for_update=True,
    )
    current_status = str(getattr(submission, "status", ""))
    if current_status in {"APPROVED", "DECLINED", "WITHDRAWN", "EXPIRED"}:
        raise _problem(
            "LENDER_SUBMISSION_FINAL",
            "A final lender submission cannot receive another decision.",
            409,
        )
    next_status = {
        "APPROVE": "APPROVED",
        "DECLINE": "DECLINED",
        "REQUEST_INFORMATION": "CONDITIONS",
    }[payload.decision]
    submission.status = next_status
    if hasattr(submission, "version"):
        submission.version = int(getattr(submission, "version", 1)) + 1
    application = await db.get(models.Application, submission.application_id)
    borrower = None
    if application is not None:
        borrower = await db.get(models.Borrower, application.borrower_id)
    if payload.decision == "REQUEST_INFORMATION" and application is not None:
        db.add(
            PortalTask(
                tenant_id=active_tenant(principal),
                application_id=application.id,
                task_type="LENDER_INFORMATION_REQUEST",
                title="Additional information requested",
                description=payload.notes,
                status="OPEN",
                priority="HIGH",
                assigned_to_subject=getattr(borrower, "subject", None),
                created_by_subject=principal.subject,
                metadata_payload={"requested_items": payload.requested_items},
            )
        )
    borrower_subject = getattr(borrower, "subject", None)
    if borrower_subject:
        db.add(
            PortalNotification(
                tenant_id=active_tenant(principal),
                recipient_subject=borrower_subject,
                notification_type="LENDER_DECISION",
                title="Application update",
                body=(
                    "A lender requested additional information."
                    if payload.decision == "REQUEST_INFORMATION"
                    else "A lender decision was recorded for your application."
                ),
                href=f"/applications/{submission.application_id}",
                metadata_payload={"submission_status": next_status},
            )
        )
    response = {
        "submission_id": str(submission.id),
        "application_id": str(submission.application_id),
        "decision": payload.decision,
        "status": next_status,
        "version": getattr(submission, "version", None),
        "live_submission_triggered": False,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    db.add(
        _construct(
            models.OutboxEvent,
            {
                "event_type": "LenderSubmissionDecisionRecorded",
                "aggregate_type": "lender_submission",
                "aggregate_id": submission.id,
                "payload": response,
                "status": "PENDING",
            },
        )
    )
    db.add(
        _construct(
            models.AuditEvent,
            {
                "actor_subject": principal.subject,
                "action": "lender_submission.decision_recorded",
                "entity_type": "lender_submission",
                "entity_id": submission.id,
                "details": {
                    "lender_id": str(lender_id),
                    "previous_status": current_status,
                    "status": next_status,
                    "requested_item_count": len(payload.requested_items),
                },
            },
        )
    )
    db.add(
        _construct(
            models.IdempotencyRecord,
            {
                "actor_subject": principal.subject,
                "route": route,
                "key": idempotency_key,
                "request_hash": request_hash,
                "response_status": 200,
                "response_body": response,
                "resource_id": submission.id,
            },
        )
    )
    await db.commit()
    return response


@router.get("/bank-analysis-queue")
async def bank_analysis_queue(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=250),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    lender_id = require_lender(user.principal)
    submissions = list(
        (
            await db.execute(
                select(models.LenderSubmission).where(
                    models.LenderSubmission.lender_id == lender_id
                )
            )
        )
        .scalars()
        .all()
    )
    application_ids = {submission.application_id for submission in submissions}
    if not application_ids:
        return []
    query = select(models.BankAnalysis).where(
        models.BankAnalysis.application_id.in_(application_ids)
    )
    if status:
        query = query.where(models.BankAnalysis.status == status.upper())
    result = await db.execute(
        query.order_by(models.BankAnalysis.created_at.desc()).limit(limit)
    )
    submission_by_application = {
        submission.application_id: submission for submission in submissions
    }
    output: list[dict[str, Any]] = []
    for analysis in result.scalars().all():
        submission = submission_by_application.get(analysis.application_id)
        output.append(
            {
                "submission": _public(
                    submission,
                    ("id", "application_id", "program_id", "status"),
                ),
                "analysis": _public(
                    analysis,
                    (
                        "id",
                        "application_id",
                        "status",
                        "analysis_type",
                        "average_monthly_revenue",
                        "average_daily_balance",
                        "negative_days",
                        "nsf_count",
                        "risk_flags",
                        "completed_at",
                        "created_at",
                    ),
                ),
            }
        )
    return output


@router.get("/portfolio")
async def lender_portfolio(
    limit: int = Query(default=250, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    lender_id = require_lender(user.principal)
    offers = list(
        (
            await db.execute(
                select(models.Offer)
                .where(models.Offer.lender_id == lender_id)
                .order_by(models.Offer.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    accepted_statuses = {"ACCEPTED", "FUNDED", "ACTIVE", "REPAID"}
    active_offers = [
        offer
        for offer in offers
        if str(getattr(offer, "status", "")) in accepted_statuses
    ]
    total_amount = sum(
        (Decimal(str(getattr(offer, "amount", 0) or 0)) for offer in active_offers),
        Decimal("0"),
    )
    return {
        "summary": {
            "offer_count": len(offers),
            "accepted_or_funded_count": len(active_offers),
            "accepted_or_funded_amount": str(total_amount),
        },
        "positions": [
            _public(
                offer,
                (
                    "id",
                    "application_id",
                    "status",
                    "amount",
                    "term_months",
                    "interest_rate",
                    "factor_rate",
                    "payment_amount",
                    "payment_frequency",
                    "accepted_at",
                    "funded_at",
                    "created_at",
                ),
            )
            for offer in active_offers
        ],
    }
