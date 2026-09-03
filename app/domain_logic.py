from datetime import UTC, datetime, timedelta
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas, services
from app.auth import Principal
from app.compliance_service import generate_adverse_action_notice


POLICY_VERSION = 2


def _requirement(
    code: str,
    label: str,
    complete: bool,
    *,
    route: str,
    category: str,
) -> dict:
    return {
        "code": code,
        "label": label,
        "category": category,
        "blocking": True,
        "complete": complete,
        "status": "COMPLETE" if complete else "ACTION_REQUIRED",
        "route": route,
    }


async def create_requirement_snapshot(
    db: AsyncSession,
    application: models.Application,
) -> models.RequirementSnapshot:
    current = await services.application_requirements(db, application)
    route_by_code = {
        "BUSINESS_INFORMATION": "/business",
        "FINANCIAL_PROFILE": "/financials",
        "OWNERS": "/owners",
        "CONSENTS": "/application",
    }
    category_by_code = {
        "BUSINESS_INFORMATION": "APPLICATION",
        "FINANCIAL_PROFILE": "APPLICATION",
        "OWNERS": "APPLICATION",
        "CONSENTS": "COMPLIANCE",
    }
    requirements = [
        {
            **item,
            "blocking": True,
            "category": category_by_code[item["code"]],
            "route": route_by_code[item["code"]],
        }
        for item in current["requirements"]
    ]

    capabilities = await services.effective_capabilities(db)
    if capabilities.get("bank.live_connection", False):
        bank = await db.scalar(
            select(models.BankConnection).where(
                models.BankConnection.application_id == application.id,
                models.BankConnection.status == "CONNECTED",
            )
        )
        requirements.append(
            _requirement(
                "BANK_CONNECTION",
                "Connect business bank account",
                bank is not None,
                route="/banking",
                category="BANKING",
            )
        )

    if capabilities.get("kyb.live_verification", False):
        verification = await db.scalar(
            select(models.Verification).where(
                models.Verification.application_id == application.id,
                models.Verification.verification_type == "BUSINESS",
                models.Verification.status == "VERIFIED",
            )
        )
        requirements.append(
            _requirement(
                "BUSINESS_VERIFICATION",
                "Business verification",
                verification is not None,
                route="/verification",
                category="VERIFICATION",
            )
        )

    completed = sum(bool(item["complete"]) for item in requirements)
    completion = int(completed / len(requirements) * 100)
    ready_for_submission = completed == len(requirements)
    ready_for_contract = application.status in {
        models.ApplicationStatus.CONDITIONS_COMPLETE,
        models.ApplicationStatus.CONTRACT_READY,
        models.ApplicationStatus.CONTRACT_SENT,
        models.ApplicationStatus.CONTRACT_SIGNED,
        models.ApplicationStatus.APPROVED_FOR_FUNDING,
        models.ApplicationStatus.FUNDS_SENT,
        models.ApplicationStatus.FUNDED,
        models.ApplicationStatus.CLOSED,
    }
    ready_for_funding = application.status in {
        models.ApplicationStatus.CONTRACT_SIGNED,
        models.ApplicationStatus.APPROVED_FOR_FUNDING,
        models.ApplicationStatus.FUNDS_SENT,
        models.ApplicationStatus.FUNDED,
        models.ApplicationStatus.CLOSED,
    }
    snapshot = models.RequirementSnapshot(
        application_id=application.id,
        policy_version=POLICY_VERSION,
        completion_percentage=completion,
        ready_for_submission=ready_for_submission,
        ready_for_contract=ready_for_contract,
        ready_for_funding=ready_for_funding,
        requirements=requirements,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


def _risk_flag(
    code: str,
    severity: str,
    weight: int,
    evidence: dict,
) -> dict:
    return {
        "code": code,
        "severity": severity,
        "weight": weight,
        "evidence": evidence,
    }


async def evaluate_fraud(
    db: AsyncSession,
    application: models.Application,
) -> models.FraudAssessment:
    lead = await db.get(models.Lead, application.lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    flags: list[dict] = []
    score = 0

    duplicate_checks = (
        (
            "DUPLICATE_EMAIL",
            15,
            models.Lead.email == lead.email,
        ),
        (
            "DUPLICATE_PHONE",
            10,
            models.Lead.phone == lead.phone,
        ),
        (
            "DUPLICATE_BUSINESS",
            15,
            func.lower(models.Lead.business_name) == lead.business_name.lower(),
        ),
    )
    for code, weight, predicate in duplicate_checks:
        count = (
            await db.scalar(
                select(func.count(models.Lead.id)).where(
                    predicate,
                    models.Lead.id != lead.id,
                )
            )
            or 0
        )
        if count:
            flags.append(
                _risk_flag(
                    code,
                    "MEDIUM",
                    weight,
                    {"other_records": count},
                )
            )
            score += weight

    recent_count = (
        await db.scalar(
            select(func.count(models.Lead.id)).where(
                models.Lead.id != lead.id,
                models.Lead.created_at >= datetime.now(UTC) - timedelta(days=7),
                or_(
                    models.Lead.email == lead.email,
                    models.Lead.phone == lead.phone,
                ),
            )
        )
        or 0
    )
    if recent_count >= 3:
        flags.append(
            _risk_flag(
                "SUBMISSION_VELOCITY",
                "HIGH",
                25,
                {"related_records_7d": recent_count},
            )
        )
        score += 25

    bank = await db.scalar(
        select(models.BankAnalysis)
        .where(models.BankAnalysis.application_id == application.id)
        .order_by(models.BankAnalysis.created_at.desc())
    )
    if bank is not None and bank.nsf_count_90d >= 6:
        flags.append(
            _risk_flag(
                "HIGH_NSF_ACTIVITY",
                "HIGH",
                20,
                {"nsf_count_90d": bank.nsf_count_90d},
            )
        )
        score += 20
    if bank is not None and bank.negative_balance_days_90d >= 11:
        flags.append(
            _risk_flag(
                "FREQUENT_NEGATIVE_BALANCES",
                "MEDIUM",
                15,
                {"negative_balance_days_90d": bank.negative_balance_days_90d},
            )
        )
        score += 15

    score = min(score, 100)
    decision = (
        "BLOCKED"
        if score >= 70
        else "REVIEW_REQUIRED"
        if score >= 35
        else "PASS"
    )
    assessment = models.FraudAssessment(
        application_id=application.id,
        policy_version=POLICY_VERSION,
        score=score,
        decision=decision,
        flags=flags,
    )
    db.add(assessment)
    await db.flush()
    return assessment


async def create_underwriting_review(
    db: AsyncSession,
    application: models.Application,
    payload: schemas.UnderwritingReviewInput,
    principal: Principal,
) -> models.UnderwritingReview:
    if payload.decision == "DECLINE" and payload.submission_id is not None and not payload.reason_codes:
        raise HTTPException(
            status_code=422,
            detail="A lender decline requires at least one specific reason code",
        )
    if payload.submission_id is not None:
        submission = await db.get(models.LenderSubmission, payload.submission_id)
        if submission is None or submission.application_id != application.id:
            raise HTTPException(
                status_code=422,
                detail="Submission does not belong to this application",
            )

    target_by_decision = {
        "APPROVE": models.ApplicationStatus.READY_FOR_MATCHING,
        "DECLINE": models.ApplicationStatus.DECLINED,
        "FRAUD_REVIEW": models.ApplicationStatus.FRAUD_REVIEW,
        "COMPLIANCE_REVIEW": models.ApplicationStatus.COMPLIANCE_REVIEW,
    }
    target = target_by_decision.get(payload.decision)
    if target is not None and application.status != target:
        services.transition_application(
            db,
            application,
            target,
            principal,
            reason=f"Underwriting decision: {payload.decision}",
        )

    review = models.UnderwritingReview(
        application_id=application.id,
        submission_id=payload.submission_id,
        reviewer_subject=principal.subject,
        decision=payload.decision,
        reason_codes=payload.reason_codes,
        notes=payload.notes,
        policy_version=POLICY_VERSION,
    )
    db.add(review)
    await db.flush()
    if payload.decision == "DECLINE" and payload.submission_id is not None:
        await generate_adverse_action_notice(db, review)
    db.add(
        models.AuditEvent(
            actor_id=principal.subject,
            action="UNDERWRITING_REVIEW",
            resource_type="application",
            resource_id=str(application.id),
            details={
                "decision": payload.decision,
                "reason_codes": payload.reason_codes,
                "review_id": str(review.id),
            },
        )
    )
    return review
