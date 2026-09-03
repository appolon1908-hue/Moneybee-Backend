"""Compliance document generation: ECOA/Regulation B adverse-action
notices, commercial-financing cost disclosures, and 1099-NEC commission
tax records.

None of this is a substitute for legal review. Each generator's docstring
says specifically what it does and doesn't cover - read those before
sending anything this produces to a real applicant or filing anything
with the IRS.
"""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select, text
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

    existing = await db.scalar(
        select(AdverseActionNotice).where(
            AdverseActionNotice.underwriting_review_id == review.id
        )
    )
    if existing is not None:
        return existing

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


_PAYMENTS_PER_YEAR = {
    "MONTHLY": Decimal(12),
    "WEEKLY": Decimal(52),
    "BIWEEKLY": Decimal(26),
    "SEMIMONTHLY": Decimal(24),
    "DAILY": Decimal(365),
}
_MONEY = Decimal("0.01")


async def get_offer_disclosure(
    db: AsyncSession, offer_id, *, lock: bool = False
) -> CommercialFinancingDisclosure | None:
    statement = select(CommercialFinancingDisclosure).where(
        CommercialFinancingDisclosure.offer_id == offer_id
    )
    if lock:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def acknowledge_offer_disclosure(
    db: AsyncSession, offer_id, *, actor: str
) -> CommercialFinancingDisclosure | None:
    disclosure = await get_offer_disclosure(db, offer_id, lock=True)
    if disclosure is not None and disclosure.acknowledged_at is None:
        disclosure.acknowledged_at = models.utcnow()
        disclosure.acknowledged_by = actor
        await db.flush()
    return disclosure


async def create_offer_with_disclosure(
    db: AsyncSession,
    values: dict,
    *,
    jurisdiction: str | None,
) -> models.Offer:
    """Persist an offer and its mandatory disclosure in one transaction."""
    offer = models.Offer(**values)
    db.add(offer)
    await db.flush()
    await generate_commercial_financing_disclosure(
        db, offer, jurisdiction=jurisdiction
    )
    return offer


def calculate_total_repayment(offer: models.Offer) -> Decimal:
    """Return an authoritative or reproducibly calculated repayment total.

    The schedule convention is 12 months, 52 weeks, 26 biweekly periods,
    24 semimonthly periods, and 365 calendar days per year. A partial payment
    period is not guessed: callers must provide ``total_repayment`` for terms
    that do not produce an integral number of payments under that convention.
    """
    if offer.total_repayment is not None:
        total = Decimal(str(offer.total_repayment))
    else:
        frequency = str(offer.payment_frequency).upper()
        payments_per_year = _PAYMENTS_PER_YEAR.get(frequency)
        if payments_per_year is None:
            raise ValueError(f"Unsupported payment frequency: {offer.payment_frequency}")
        payment = Decimal(str(offer.payment_amount))
        if payment <= 0 or offer.term_months <= 0:
            raise ValueError("Payment amount and term must be positive")
        payment_count = Decimal(offer.term_months) * payments_per_year / Decimal(12)
        if payment_count != payment_count.to_integral_value():
            raise ValueError(
                "Payment schedule has a partial period; provide total_repayment explicitly"
            )
        total = payment * payment_count
    try:
        total = total.quantize(_MONEY, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Total repayment cannot be represented as money") from exc
    if total <= 0:
        raise ValueError("Total repayment must be positive")
    return total


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
    total_repayment = calculate_total_repayment(offer)
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


async def lock_commission_tax_year(db: AsyncSession, tax_year: int) -> None:
    """Serialize every generator/filer touching a tax year in PostgreSQL."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(
            hashlib.sha256(f"commission-tax-records:{tax_year}".encode()).digest()[:8],
            "big",
        ) & ((1 << 63) - 1)
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})


async def generate_commission_tax_records(db: AsyncSession, tax_year: int) -> list[CommissionTaxRecord]:
    """Aggregates CommissionSplit amounts per recipient for one tax year
    into the data a 1099-NEC (Box 1: Nonemployee compensation) would be
    filed from. requires_1099 follows the federal $600 threshold (IRC
    Sec. 6041 as it applies to nonemployee compensation) - state filing
    thresholds can be lower and aren't accounted for.

    Only split rows carrying durable payment evidence (status PAID,
    paid_at, and a provider/accounting payment reference) contribute.
    Merely allocating a split is not reportable compensation.

    Idempotent: re-running for a year replaces each recipient's totals
    rather than accumulating, since it always recomputes from
    CommissionSplit rows. Does NOT submit anything to the IRS or a filing
    service - a real e-file integration (e.g. Track1099, Tax1099, or the
    IRS FIRE system) is a separate, further integration this only
    produces the input for. TINs, when supplied via
    update_recipient_tin(), are stored encrypted with app/encryption.py's
    versioned scheme and never returned in the clear by any endpoint
    built so far."""
    await lock_commission_tax_year(db, tax_year)

    year_start = datetime(tax_year, 1, 1, tzinfo=UTC)
    year_end = datetime(tax_year + 1, 1, 1, tzinfo=UTC)
    rows = (
        await db.execute(
            select(
                models.CommissionSplit.recipient_type,
                models.CommissionSplit.recipient_reference,
                models.CommissionSplit.amount,
            ).where(
                models.CommissionSplit.status == "PAID",
                models.CommissionSplit.paid_at.is_not(None),
                models.CommissionSplit.payment_reference.is_not(None),
                models.CommissionSplit.paid_at >= year_start,
                models.CommissionSplit.paid_at < year_end,
            )
        )
    ).all()

    totals: dict[tuple[str, str], dict] = {}
    for recipient_type, recipient_reference, receipt_amount in rows:
        key = (recipient_type, recipient_reference)
        bucket = totals.setdefault(key, {"total": Decimal("0"), "count": 0})
        bucket["total"] += Decimal(str(receipt_amount))
        bucket["count"] += 1

    existing_rows = list((await db.scalars(
        select(CommissionTaxRecord)
        .where(CommissionTaxRecord.tax_year == tax_year)
        .with_for_update()
    )).all())
    existing_by_key = {
        (row.recipient_type, row.recipient_reference): row for row in existing_rows
    }
    results: list[CommissionTaxRecord] = []
    for recipient_type, recipient_reference in sorted(set(totals) | set(existing_by_key)):
        bucket = totals.get((recipient_type, recipient_reference), {"total": Decimal("0"), "count": 0})
        existing = existing_by_key.get((recipient_type, recipient_reference))
        total_amount = bucket["total"]
        requires_1099 = total_amount >= _FORM_1099_NEC_THRESHOLD
        if existing is not None:
            regenerated = (total_amount, bucket["count"], requires_1099)
            persisted = (
                Decimal(str(existing.total_amount)),
                existing.commission_count,
                existing.requires_1099,
            )
            if existing.filed_at is not None and regenerated != persisted:
                raise ValueError(
                    "Filed commission tax records are immutable; create a controlled "
                    "amendment before regenerating this recipient and tax year"
                )
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
    if record.filed_at is not None:
        raise ValueError(
            "Filed recipient identity is immutable; create a controlled amendment first"
        )
    record.recipient_name = recipient_name
    record.tin_ciphertext = encrypt_secret(tin)
    await db.flush()
    return record
