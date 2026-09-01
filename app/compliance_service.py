"""Compliance document generation: ECOA/Regulation B adverse-action
notices, commercial-financing cost disclosures, and 1099-NEC commission
tax records.

None of this is a substitute for legal review. Each generator's docstring
says specifically what it does and doesn't cover - read those before
sending anything this produces to a real applicant or filing anything
with the IRS.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import identity_models, models
from app.compliance_models import (
    AdverseActionNotice,
    CommercialFinancingDisclosure,
    CommissionTaxRecord,
)
from app.encryption import encrypt_secret


# ECOA's required notice text (12 CFR Part 1002, Regulation B, Appendix C
# Model Form C-1). This paragraph is reproduced close to verbatim from the
# regulation - it is the one part of this notice that should NOT be
# reworded. The bracketed federal-agency line varies by creditor type
# (bank vs. non-bank, and by which regulator has jurisdiction) and is
# deliberately left as a fill-in rather than guessed at.
_ECOA_NOTICE = (
    "The federal Equal Credit Opportunity Act prohibits creditors from "
    "discriminating against credit applicants on the basis of race, color, "
    "religion, national origin, sex, marital status, age (provided the "
    "applicant has the capacity to enter into a binding contract); because "
    "all or part of the applicant's income derives from any public "
    "assistance program; or because the applicant has in good faith "
    "exercised any right under the Consumer Credit Protection Act. The "
    "federal agency that administers compliance with this law concerning "
    "this creditor is [FEDERAL AGENCY NAME AND ADDRESS - fill in based on "
    "the creditor's regulator before sending]."
)


def _humanize_reason(code: str) -> str:
    return code.replace("_", " ").strip().capitalize()


async def generate_adverse_action_notice(
    db: AsyncSession,
    review: models.UnderwritingReview,
) -> AdverseActionNotice:
    """Generates (and persists) an adverse-action notice for a DECLINE
    underwriting decision. Covers the notice elements Regulation B
    Sec. 1002.9(a)(2) requires for a written notice: a statement that
    adverse action was taken, the creditor's identity, the principal
    reasons, and the ECOA notice. Does NOT cover: the business-credit
    exception for applicants with >$1MM prior-year gross revenue (Sec.
    1002.9(a)(3), which permits a shorter notice) - this always generates
    the fuller notice; FCRA score-disclosure requirements, which apply
    only if a credit score was actually used in the decision and aren't
    wired in here since this system doesn't yet track that per-decision;
    or delivery (mail/email) - status stays "GENERATED" until something
    else marks it "SENT"."""
    if review.decision != "DECLINE":
        raise ValueError("Adverse-action notices are only generated for DECLINE decisions")
    if review.submission_id is None:
        raise ValueError("Underwriting review has no associated lender submission")

    submission = await db.get(models.LenderSubmission, review.submission_id)
    if submission is None:
        raise ValueError("Lender submission not found")
    application = await db.get(models.Application, review.application_id)
    if application is None:
        raise ValueError("Application not found")
    business = await db.scalar(
        select(models.Business).where(models.Business.application_id == application.id)
    )
    lead = await db.get(models.Lead, application.lead_id) if application.lead_id else None

    creditor = await db.get(identity_models.Organization, submission.lender_id)
    creditor_name = creditor.name if creditor is not None else "the participating lender"

    applicant_name = (
        business.legal_name if business is not None
        else (lead.business_name if lead is not None else "the applicant")
    )
    reasons = [_humanize_reason(code) for code in review.reason_codes] or [
        "No specific reason codes were recorded for this decision."
    ]

    generated_on = datetime.now(UTC).date().isoformat()
    reasons_block = "\n".join(f"  - {reason}" for reason in reasons)
    notice_text = (
        f"Date: {generated_on}\n\n"
        f"To: {applicant_name}\n\n"
        f"NOTICE OF ADVERSE ACTION\n\n"
        f"{creditor_name} has taken adverse action on your application for "
        f"business credit. This means your application was declined.\n\n"
        f"The specific principal reason(s) for this decision were:\n"
        f"{reasons_block}\n\n"
        f"If you would like a further statement of the specific reasons for "
        f"this decision, you may request one within 60 days of this notice "
        f"by contacting {creditor_name}.\n\n"
        f"{_ECOA_NOTICE}\n"
    )

    notice = AdverseActionNotice(
        application_id=application.id,
        submission_id=submission.id,
        underwriting_review_id=review.id,
        lender_id=submission.lender_id,
        creditor_name=creditor_name,
        principal_reasons=reasons,
        notice_text=notice_text,
        status="GENERATED",
    )
    db.add(notice)
    await db.flush()
    return notice


# --- Commercial financing disclosure -----------------------------------


async def generate_commercial_financing_disclosure(
    db: AsyncSession,
    offer: models.Offer,
    *,
    jurisdiction: str | None = None,
) -> CommercialFinancingDisclosure:
    """Computes and persists the cost-disclosure figures several states'
    commercial-financing disclosure laws require before a business can
    accept an offer (California SB 1235 / Cal. Fin. Code Sec. 22800 et
    seq. is the model most other states' laws follow; New York, Utah,
    Virginia, Florida, and Georgia have their own variants with different
    triggers and formats). The arithmetic here - amount financed, finance
    charge, total repayment, an APR figure, payment schedule, prepayment
    policy - is real and correct for a simple-interest/factor-rate
    product. What this does NOT do: select the state-specific template,
    layout, and required disclosure register/registration a given
    jurisdiction mandates, or determine which offers a given jurisdiction
    even covers (thresholds and exemptions vary). Treat jurisdiction as
    informational until a lawyer maps it to a real per-state template."""
    amount_financed = Decimal(str(offer.amount))
    total_repayment = (
        Decimal(str(offer.total_repayment))
        if offer.total_repayment is not None
        else Decimal(str(offer.payment_amount)) * offer.term_months
    )
    finance_charge = total_repayment - amount_financed

    if offer.apr is not None:
        estimated_apr = Decimal(str(offer.apr))
    elif amount_financed > 0 and offer.term_months > 0:
        # A simple average-annualized-rate approximation for products
        # priced as a factor rate rather than an APR (e.g. amount * factor
        # - amount) / amount, annualized over the term. This is NOT a
        # federal Truth-in-Lending APR (which requires actuarial/US-Rule
        # amortization) - it's the "APR-equivalent" some state disclosure
        # laws accept as an estimate. Flag it as estimated in the text.
        term_years = Decimal(offer.term_months) / Decimal(12)
        estimated_apr = (
            (finance_charge / amount_financed) / term_years * 100
            if term_years > 0
            else Decimal("0")
        )
    else:
        estimated_apr = None

    prepayment_policy = (
        offer.prepayment_terms
        if offer.prepayment_terms
        else "No prepayment discount or penalty terms were specified for this offer."
    )

    apr_line = (
        f"Estimated APR: {estimated_apr:.2f}%\n"
        if estimated_apr is not None
        else "Estimated APR: not available\n"
    )
    disclosure_text = (
        f"COMMERCIAL FINANCING DISCLOSURE (estimate)\n\n"
        f"Total amount financed: ${amount_financed:,.2f}\n"
        f"Finance charge: ${finance_charge:,.2f}\n"
        f"Total repayment amount: ${total_repayment:,.2f}\n"
        f"{apr_line}"
    )
    disclosure_text += (
        f"Payment: ${Decimal(str(offer.payment_amount)):,.2f} {offer.payment_frequency.lower()}\n"
        f"Term: {offer.term_months} months\n"
        f"Prepayment policy: {prepayment_policy}\n"
    )

    disclosure = CommercialFinancingDisclosure(
        offer_id=offer.id,
        application_id=offer.application_id,
        jurisdiction=jurisdiction,
        amount_financed=amount_financed,
        finance_charge=finance_charge,
        total_repayment_amount=total_repayment,
        estimated_apr=estimated_apr,
        payment_amount=Decimal(str(offer.payment_amount)),
        payment_frequency=offer.payment_frequency,
        term_months=offer.term_months,
        prepayment_policy=prepayment_policy,
        disclosure_text=disclosure_text,
    )
    db.add(disclosure)
    await db.flush()
    return disclosure


# --- 1099-NEC commission tax records ------------------------------------


_FORM_1099_NEC_THRESHOLD = Decimal("600")


async def generate_commission_tax_records(db: AsyncSession, tax_year: int) -> list[CommissionTaxRecord]:
    """Aggregates CommissionSplit amounts per recipient for one tax year
    into the data a 1099-NEC (Box 1: Nonemployee compensation) would be
    filed from. requires_1099 follows the federal $600 threshold (IRC
    Sec. 6041 as it applies to nonemployee compensation) - state filing
    thresholds can be lower and aren't accounted for.

    Attribution caveat: there is no dedicated commission-receipt ledger
    table in this schema (POST /admin/commissions/{id}/receipts just
    increments Commission.received_amount and logs an AuditEvent) and no
    split-level "paid" status or date - CommissionSplit.status is set to
    "PENDING" on creation and nothing ever transitions it. This uses
    CommissionSplit.created_at as the tax-year attribution date, which
    approximates but does not guarantee "when the recipient was actually
    paid." Wiring a real split-disbursement workflow (naturally, through
    the payment adapters added alongside this) would let this generator
    key off an actual payment date instead - worth doing before this
    runs against real payout data.

    Idempotent: re-running for a year replaces each recipient's totals
    rather than accumulating, since it always recomputes from
    CommissionSplit rows. Does NOT submit anything to the IRS or a filing
    service - a real e-file integration (e.g. Track1099, Tax1099, or the
    IRS FIRE system) is a separate, further integration this only
    produces the input for. TINs, when supplied via
    update_recipient_tin(), are stored encrypted with app/encryption.py's
    versioned scheme and never returned in the clear by any endpoint
    built so far."""
    year_start = datetime(tax_year, 1, 1, tzinfo=UTC)
    year_end = datetime(tax_year + 1, 1, 1, tzinfo=UTC)
    rows = (
        await db.execute(
            select(
                models.CommissionSplit.recipient_type,
                models.CommissionSplit.recipient_reference,
                models.CommissionSplit.amount,
            ).where(
                models.CommissionSplit.created_at >= year_start,
                models.CommissionSplit.created_at < year_end,
            )
        )
    ).all()

    totals: dict[tuple[str, str], dict] = {}
    for recipient_type, recipient_reference, receipt_amount in rows:
        key = (recipient_type, recipient_reference)
        bucket = totals.setdefault(key, {"total": Decimal("0"), "count": 0})
        bucket["total"] += Decimal(str(receipt_amount))
        bucket["count"] += 1

    results: list[CommissionTaxRecord] = []
    for (recipient_type, recipient_reference), bucket in totals.items():
        existing = await db.scalar(
            select(CommissionTaxRecord).where(
                CommissionTaxRecord.recipient_reference == recipient_reference,
                CommissionTaxRecord.tax_year == tax_year,
            )
        )
        total_amount = bucket["total"]
        requires_1099 = total_amount >= _FORM_1099_NEC_THRESHOLD
        if existing is not None:
            existing.recipient_type = recipient_type
            existing.total_amount = total_amount
            existing.commission_count = bucket["count"]
            existing.requires_1099 = requires_1099
            results.append(existing)
        else:
            record = CommissionTaxRecord(
                recipient_type=recipient_type,
                recipient_reference=recipient_reference,
                tax_year=tax_year,
                total_amount=total_amount,
                commission_count=bucket["count"],
                requires_1099=requires_1099,
            )
            db.add(record)
            results.append(record)
    await db.flush()
    return results


async def update_recipient_tin(
    db: AsyncSession,
    record: CommissionTaxRecord,
    *,
    recipient_name: str,
    tin: str,
) -> CommissionTaxRecord:
    record.recipient_name = recipient_name
    record.tin_ciphertext = encrypt_secret(tin)
    await db.flush()
    return record
