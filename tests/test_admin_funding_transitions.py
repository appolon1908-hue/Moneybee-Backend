import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.main import app


def _accept_an_offer_and_build_funding(client: TestClient) -> str:
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
            "business_name": "Funding Transition Test Co",
            "first_name": "Fay",
            "last_name": "Ledger",
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
            "legal_name": "Funding Transition Test Co LLC",
            "dba": "Funding Transition Test Co",
            "entity_type": "LLC",
            "state_formed": "FL",
            "industry": "TRANSPORTATION",
            "website": "https://example.com",
            "address": {"city": "Miami", "state": "FL"},
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
            "first_name": "Fay",
            "last_name": "Ledger",
            "ownership_percent": 100,
            "title": "Owner",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550199",
            "address": {"city": "Miami", "state": "FL"},
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
    offer_id = client.post(
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
        },
    ).json()["id"]
    accepted = client.post(
        f"/api/v2/offers/{offer_id}/accept",
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert accepted.status_code == 200

    funding = client.get(f"/api/v2/applications/{application_id}/funding")
    assert funding.status_code == 200
    return funding.json()["id"]


async def _set_funding_status(funding_id: str, status: str) -> None:
    async with SessionLocal() as db:
        funding = await db.get(models.Funding, uuid.UUID(funding_id))
        funding.status = status
        await db.commit()


async def test_funding_rejects_invalid_transition():
    with TestClient(app) as client:
        funding_id = _accept_an_offer_and_build_funding(client)

        # Fresh funding starts at CONDITIONS_PENDING; approve requires
        # CONTRACT_SIGNED (the Contract engine isn't built yet, so nothing
        # can legitimately reach that state through the real API today).
        response = client.post(
            f"/api/v2/admin/fundings/{funding_id}/approve",
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "INVALID_FUNDING_TRANSITION"
        assert response.json()["detail"]["allowed"] == [
            "CANCELLED",
            "CONDITIONS_SATISFIED",
            "DECLINED",
        ]


async def test_funding_full_transition_sequence_and_commission_creation():
    with TestClient(app) as client:
        funding_id = _accept_an_offer_and_build_funding(client)
        await _set_funding_status(funding_id, "CONTRACT_SIGNED")

        approve_key = uuid.uuid4().hex
        approved = client.post(
            f"/api/v2/admin/fundings/{funding_id}/approve",
            headers={"Idempotency-Key": approve_key},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED_FOR_FUNDING"

        # Replay is idempotent.
        replay = client.post(
            f"/api/v2/admin/fundings/{funding_id}/approve",
            headers={"Idempotency-Key": approve_key},
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "APPROVED_FOR_FUNDING"

        funds_sent = client.post(
            f"/api/v2/admin/fundings/{funding_id}/funds-sent",
            json={"provider_reference": "WIRE-REF-12345"},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert funds_sent.status_code == 200
        assert funds_sent.json()["status"] == "FUNDS_SENT"
        assert funds_sent.json()["provider_reference"] == "WIRE-REF-12345"

        confirmed = client.post(
            f"/api/v2/admin/fundings/{funding_id}/confirm",
            json={"funded_amount": "50000.00", "commission_rate_bps": 800},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "FUNDED"
        assert confirmed.json()["funded_amount"] == "50000.00"
        assert confirmed.json()["funding_confirmed_at"] is not None

        # Confirming created exactly one Commission at 8% of funded_amount.
        commissions = client.get("/api/v2/admin/commissions").json()
        commission = next(
            item for item in commissions if item["funding_id"] == funding_id
        )
        assert commission["expected_amount"] == "4000.00"
        assert commission["status"] == "EXPECTED"

        # FUNDED is terminal.
        terminal = client.post(
            f"/api/v2/admin/fundings/{funding_id}/approve",
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert terminal.status_code == 409


async def test_funding_can_be_declined_with_a_reason():
    with TestClient(app) as client:
        funding_id = _accept_an_offer_and_build_funding(client)

        declined = client.post(
            f"/api/v2/admin/fundings/{funding_id}/decline",
            json={"reason": "Applicant withdrew after offer acceptance."},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert declined.status_code == 200
        assert declined.json()["status"] == "DECLINED"
