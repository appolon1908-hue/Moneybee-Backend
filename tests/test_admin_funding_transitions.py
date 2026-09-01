import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.main import app


def _prepare_matched_submission(client: TestClient) -> tuple[str, str, str, str]:
    """Builds a submitted, matched application through to a ready-to-offer
    lender submission. Returns (application_id, submission_id, lender_id,
    program_id)."""
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
    return application_id, submission_id, lender_id, program_id


def _create_and_accept_offer(
    client: TestClient,
    application_id: str,
    submission_id: str,
    lender_id: str,
    program_id: str,
) -> str:
    """Creates and accepts an offer on an already-matched submission.
    Returns the funding_id."""
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


def _accept_an_offer_and_build_funding(client: TestClient) -> str:
    application_id, submission_id, lender_id, program_id = _prepare_matched_submission(
        client
    )
    return _create_and_accept_offer(
        client, application_id, submission_id, lender_id, program_id
    )


async def _set_funding_status(funding_id: str, status: str) -> None:
    async with SessionLocal() as db:
        funding = await db.get(models.Funding, uuid.UUID(funding_id))
        funding.status = status
        await db.commit()


async def test_funding_auto_advances_to_conditions_satisfied_with_no_conditions():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = (
            _prepare_matched_submission(client)
        )
        funding_id = _create_and_accept_offer(
            client, application_id, submission_id, lender_id, program_id
        )
        # The submission behind this funding never had any conditions
        # attached, so acceptance should vacuously satisfy them immediately.
        funding = client.get(f"/api/v2/applications/{application_id}/funding")
        assert funding.json()["status"] == "CONDITIONS_SATISFIED"

        # approve still correctly requires CONTRACT_SIGNED, not reachable yet.
        response = client.post(
            f"/api/v2/admin/fundings/{funding_id}/approve",
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "INVALID_FUNDING_TRANSITION"
        assert response.json()["context"]["allowed"] == [
            "CANCELLED",
            "CONTRACT_SIGNED",
            "DECLINED",
        ]


async def test_funding_stays_pending_until_last_condition_satisfied():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = (
            _prepare_matched_submission(client)
        )
        condition_id = client.post(
            f"/api/v2/lender/submissions/{submission_id}/conditions",
            json={"description": "Provide the most recent bank statement."},
        ).json()["id"]

        _create_and_accept_offer(
            client, application_id, submission_id, lender_id, program_id
        )

        # A condition exists and isn't satisfied yet - funding must not advance.
        funding = client.get(f"/api/v2/applications/{application_id}/funding")
        assert funding.json()["status"] == "CONDITIONS_PENDING"

        client.post(f"/api/v2/conditions/{condition_id}/submit")
        approved = client.post(f"/api/v2/lender/conditions/{condition_id}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "SATISFIED"

        # The only condition is now satisfied - funding should have advanced.
        funding = client.get(f"/api/v2/applications/{application_id}/funding")
        assert funding.json()["status"] == "CONDITIONS_SATISFIED"


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


async def test_funds_sent_rejects_a_second_call_with_a_fresh_idempotency_key():
    """A replay with the SAME key is idempotent (see above). But a second,
    genuinely new call after FUNDS_SENT has already been reached must not
    silently re-execute the side effects (overwriting provider_reference/
    funds_sent_at) - it should 409 instead."""
    with TestClient(app) as client:
        funding_id = _accept_an_offer_and_build_funding(client)
        await _set_funding_status(funding_id, "CONTRACT_SIGNED")
        client.post(
            f"/api/v2/admin/fundings/{funding_id}/approve",
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        first = client.post(
            f"/api/v2/admin/fundings/{funding_id}/funds-sent",
            json={"provider_reference": "WIRE-REF-ORIGINAL"},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert first.status_code == 200
        assert first.json()["provider_reference"] == "WIRE-REF-ORIGINAL"

        second = client.post(
            f"/api/v2/admin/fundings/{funding_id}/funds-sent",
            json={"provider_reference": "WIRE-REF-SHOULD-NOT-STICK"},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert second.status_code == 409
        assert second.json()["code"] == "FUNDING_ALREADY_FUNDS_SENT"

        fundings = client.get("/api/v2/admin/fundings").json()
        unchanged = next(item for item in fundings if item["id"] == funding_id)
        assert unchanged["provider_reference"] == "WIRE-REF-ORIGINAL"


async def test_confirm_rejects_a_second_call_with_a_fresh_idempotency_key():
    """Same class of bug as funds-sent: confirming twice with different
    idempotency keys must not create a second Commission row."""
    with TestClient(app) as client:
        funding_id = _accept_an_offer_and_build_funding(client)
        await _set_funding_status(funding_id, "CONTRACT_SIGNED")
        client.post(
            f"/api/v2/admin/fundings/{funding_id}/approve",
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        client.post(
            f"/api/v2/admin/fundings/{funding_id}/funds-sent",
            json={"provider_reference": "WIRE-REF-12345"},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        first = client.post(
            f"/api/v2/admin/fundings/{funding_id}/confirm",
            json={"funded_amount": "50000.00", "commission_rate_bps": 800},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v2/admin/fundings/{funding_id}/confirm",
            json={"funded_amount": "50000.00", "commission_rate_bps": 800},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert second.status_code == 409
        assert second.json()["code"] == "FUNDING_ALREADY_FUNDED"

        commissions = client.get("/api/v2/admin/commissions").json()
        matches = [item for item in commissions if item["funding_id"] == funding_id]
        assert len(matches) == 1


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
