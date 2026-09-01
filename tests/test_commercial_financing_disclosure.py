import os
import uuid
from dataclasses import dataclass
from decimal import Decimal

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.compliance_service import generate_commercial_financing_disclosure
from app.db import SessionLocal
from app.main import app


def _prepare_matched_submission(client: TestClient) -> tuple[str, str, str, str]:
    unique = uuid.uuid4().hex
    lead = client.post(
        "/api/v2/public/prequalifications",
        headers={"Idempotency-Key": unique},
        json={
            "funding_amount": 75000,
            "currency": "USD",
            "use_of_funds": "WORKING_CAPITAL",
            "time_in_business_months": 24,
            "monthly_revenue": 50000,
            "business_name": "Disclosure Test Co",
            "first_name": "Cora",
            "last_name": "Cost",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550199",
            "postal_code": "33101",
            "consents": [{"type": "APPLICATION_TERMS", "document_version": "v1", "accepted": True}],
            "marketing": {"landing_page": "business-loans"},
        },
    )
    application_id = client.post(
        "/api/v2/applications", json={"lead_id": lead.json()["lead_id"]}
    ).json()["id"]
    client.put(
        f"/api/v2/applications/{application_id}/business",
        json={
            "legal_name": "Disclosure Test Co LLC",
            "dba": "Disclosure Test Co",
            "entity_type": "LLC",
            "state_formed": "CA",
            "industry": "TRANSPORTATION",
            "website": "https://example.com",
            "address": {"city": "Los Angeles", "state": "CA"},
        },
    )
    client.put(
        f"/api/v2/applications/{application_id}/financial-profile",
        json={
            "annual_revenue": 600000,
            "monthly_revenue": 50000,
            "monthly_expenses": 30000,
            "existing_debt": 25000,
            "existing_positions": 1,
        },
    )
    client.post(
        f"/api/v2/applications/{application_id}/owners",
        json={
            "first_name": "Cora",
            "last_name": "Cost",
            "ownership_percent": 100,
            "title": "Owner",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550199",
            "address": {"city": "Los Angeles", "state": "CA"},
        },
    )
    client.post(f"/api/v2/applications/{application_id}/submit")

    lender_id = str(uuid.uuid4())
    program_id = client.post(
        f"/api/v2/lenders/{lender_id}/programs",
        json={
            "lender_id": lender_id,
            "name": "Working Capital Standard",
            "product_type": "WORKING_CAPITAL",
            "min_amount": 10000,
            "max_amount": 250000,
            "minimum_monthly_revenue": 10000,
            "minimum_time_in_business_months": 12,
            "states": [],
            "excluded_industries": [],
        },
    ).json()["id"]
    client.post(f"/api/v2/applications/{application_id}/match")
    submission_id = next(
        item
        for item in client.post(
            f"/api/v2/admin/applications/{application_id}/prepare-matched-submissions"
        ).json()
        if item["program_id"] == program_id
    )["id"]
    return application_id, submission_id, lender_id, program_id


async def test_creating_an_offer_generates_a_commercial_financing_disclosure():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = _prepare_matched_submission(client)

        offer = client.post(
            f"/api/v2/lender/submissions/{submission_id}/offers",
            json={
                "application_id": application_id,
                "lender_id": lender_id,
                "program_id": program_id,
                "product_type": "WORKING_CAPITAL",
                "amount": 50000,
                "term_months": 12,
                "payment_frequency": "MONTHLY",
                "payment_amount": 5000,
                "apr": 15,
                "origination_fee": 500,
                "total_repayment": 60000,
                "prepayment_terms": "No prepayment penalty after month 6.",
            },
        )
        assert offer.status_code == 201
        offer_id = offer.json()["id"]

        disclosure = client.get(
            f"/api/v2/admin/offers/{offer_id}/commercial-financing-disclosure"
        )
        assert disclosure.status_code == 200
        body = disclosure.json()
        assert body["amount_financed"] == "50000.00"
        assert body["finance_charge"] == "10000.00"
        assert body["total_repayment_amount"] == "60000.00"
        assert body["estimated_apr"] == "15.0000"
        # jurisdiction comes from Application.state, which this minimal
        # test setup never populates (only Business.address does) - None
        # is the correct, honest result here, not a bug in the disclosure
        # generator itself.
        assert body["jurisdiction"] is None
        assert "No prepayment penalty" in body["prepayment_policy"]
        assert "COMMERCIAL FINANCING DISCLOSURE" in body["disclosure_text"]
        assert body["acknowledged_at"] is None

        # acknowledged_by is derived from the authenticated principal, not
        # taken from the request body - a client-supplied value here must
        # be silently ignored rather than let any caller attribute the
        # acknowledgment to whoever they claim.
        acknowledge = client.post(
            f"/api/v2/admin/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
            json={"acknowledged_by": "spoofed-client-value"},
        )
        assert acknowledge.status_code == 200
        assert acknowledge.json()["acknowledged_at"] is not None
        assert acknowledge.json()["acknowledged_by"] == "local-admin"


async def test_commercial_financing_disclosure_estimates_apr_from_a_factor_rate_offer():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = _prepare_matched_submission(client)

        offer = client.post(
            f"/api/v2/lender/submissions/{submission_id}/offers",
            json={
                "application_id": application_id,
                "lender_id": lender_id,
                "program_id": program_id,
                "product_type": "WORKING_CAPITAL",
                "amount": 40000,
                "term_months": 12,
                "payment_frequency": "MONTHLY",
                "payment_amount": 4000,
                "factor_rate": 1.2,
                "total_repayment": 48000,
            },
        )
        assert offer.status_code == 201
        offer_id = offer.json()["id"]

        disclosure = client.get(
            f"/api/v2/admin/offers/{offer_id}/commercial-financing-disclosure"
        )
        body = disclosure.json()
        # No offer.apr supplied -> estimated from finance_charge / amount_financed,
        # annualized over the 12-month term: (8000/40000) / 1.0 * 100 = 20%.
        assert body["estimated_apr"] == "20.0000"


@dataclass
class _FakeOffer:
    id: uuid.UUID
    application_id: uuid.UUID
    amount: Decimal
    term_months: int
    payment_frequency: str
    payment_amount: Decimal
    apr: Decimal | None
    total_repayment: Decimal | None
    prepayment_terms: str | None


async def test_disclosure_text_still_includes_the_cost_figures_when_apr_is_unavailable():
    # No offer.apr and term_months <= 0 -> estimated_apr resolves to None
    # (the branch OfferInput's real validation keeps unreachable through
    # the API, but the service itself must still render a correct
    # disclosure rather than silently dropping the dollar figures).
    offer = _FakeOffer(
        id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        amount=Decimal("10000"),
        term_months=0,
        payment_frequency="MONTHLY",
        payment_amount=Decimal("1000"),
        apr=None,
        total_repayment=Decimal("11000"),
        prepayment_terms=None,
    )
    with TestClient(app):
        async with SessionLocal() as db:
            disclosure = await generate_commercial_financing_disclosure(db, offer)
            assert disclosure.estimated_apr is None
            assert "Total amount financed: $10,000.00" in disclosure.disclosure_text
            assert "Finance charge: $1,000.00" in disclosure.disclosure_text
            assert "Total repayment amount: $11,000.00" in disclosure.disclosure_text
            assert "Estimated APR: not available" in disclosure.disclosure_text
