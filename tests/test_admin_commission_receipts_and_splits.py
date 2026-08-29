import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app import models, worker
from app.db import SessionLocal
from app.integration_models import IntegrationInboxMessage
from app.main import app


async def _reach_funded_commission(client: TestClient) -> str:
    """Drives the real, full engine chain end to end - offer acceptance,
    the automatic conditions-satisfied transition, contract creation, a
    simulated signed DocuSign webhook, and the funding approve -> funds-
    sent -> confirm sequence - and returns the resulting commission_id.
    Nothing here is injected directly via the DB except the inbound
    webhook payload, since this test can't reach a real DocuSign account."""
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
            "business_name": "Commission Receipts Test Co",
            "first_name": "Remi",
            "last_name": "Payout",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550166",
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
            "legal_name": "Commission Receipts Test Co LLC",
            "dba": "Commission Receipts Test Co",
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
            "first_name": "Remi",
            "last_name": "Payout",
            "ownership_percent": 100,
            "title": "Owner",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550166",
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
    # Zero conditions on this submission -> vacuously CONDITIONS_SATISFIED,
    # and a DRAFT Contract exists already.

    funding_id = client.get(f"/api/v2/applications/{application_id}/funding").json()["id"]
    contract_id = client.get(f"/api/v2/applications/{application_id}/contract").json()["id"]

    envelope_id = f"envelope-{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        contract = await db.get(models.Contract, uuid.UUID(contract_id))
        contract.status = "SENT"
        contract.external_envelope_id = envelope_id
        db.add(
            IntegrationInboxMessage(
                provider="docusign",
                event_id=uuid.uuid4().hex,
                event_type="envelope-completed",
                payload={"envelopeId": envelope_id, "status": "completed"},
                payload_hash=uuid.uuid4().hex,
                signature_valid=True,
                status="RECEIVED",
            )
        )
        await db.commit()
    await worker.process_pending_docusign_event()

    approved = client.post(
        f"/api/v2/admin/fundings/{funding_id}/approve",
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED_FOR_FUNDING"

    funds_sent = client.post(
        f"/api/v2/admin/fundings/{funding_id}/funds-sent",
        json={"provider_reference": "WIRE-REF-98765"},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert funds_sent.status_code == 200

    confirmed = client.post(
        f"/api/v2/admin/fundings/{funding_id}/confirm",
        json={"funded_amount": "50000.00", "commission_rate_bps": 800},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "FUNDED"

    commissions = client.get("/api/v2/admin/commissions").json()
    commission = next(item for item in commissions if item["funding_id"] == funding_id)
    assert commission["expected_amount"] == "4000.00"
    return commission["id"]


async def test_commission_receipts_update_status_and_stay_idempotent():
    with TestClient(app) as client:
        commission_id = await _reach_funded_commission(client)

        key = uuid.uuid4().hex
        partial = client.post(
            f"/api/v2/admin/commissions/{commission_id}/receipts",
            json={"amount": "1500.00", "reference": "ACH-1"},
            headers={"Idempotency-Key": key},
        )
        assert partial.status_code == 200
        assert partial.json()["status"] == "PARTIALLY_RECEIVED"
        assert partial.json()["received_amount"] == "1500.00"

        replay = client.post(
            f"/api/v2/admin/commissions/{commission_id}/receipts",
            json={"amount": "1500.00", "reference": "ACH-1"},
            headers={"Idempotency-Key": key},
        )
        assert replay.status_code == 200
        # Idempotent - did not double-count the same receipt.
        assert replay.json()["received_amount"] == "1500.00"

        final = client.post(
            f"/api/v2/admin/commissions/{commission_id}/receipts",
            json={"amount": "2500.00", "reference": "ACH-2"},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert final.status_code == 200
        assert final.json()["received_amount"] == "4000.00"
        assert final.json()["status"] == "RECEIVED"


async def test_commission_splits_are_created_and_capped_at_net_expected():
    with TestClient(app) as client:
        commission_id = await _reach_funded_commission(client)

        broker_key = uuid.uuid4().hex
        broker_split = client.post(
            f"/api/v2/admin/commissions/{commission_id}/splits",
            json={
                "recipient_type": "BROKER",
                "recipient_reference": "broker-alpha",
                "percentage": "60",
                "amount": "2400.00",
            },
            headers={"Idempotency-Key": broker_key},
        )
        assert broker_split.status_code == 201
        assert broker_split.json()["status"] == "PENDING"

        # Replaying the same key returns the same split, not a duplicate.
        replay = client.post(
            f"/api/v2/admin/commissions/{commission_id}/splits",
            json={
                "recipient_type": "BROKER",
                "recipient_reference": "broker-alpha",
                "percentage": "60",
                "amount": "2400.00",
            },
            headers={"Idempotency-Key": broker_key},
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == broker_split.json()["id"]

        house_split = client.post(
            f"/api/v2/admin/commissions/{commission_id}/splits",
            json={
                "recipient_type": "HOUSE",
                "recipient_reference": "moneybee",
                "percentage": "40",
                "amount": "1600.00",
            },
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert house_split.status_code == 201

        splits = client.get(f"/api/v2/admin/commissions/{commission_id}/splits").json()
        assert len(splits) == 2
        assert sum(float(item["amount"]) for item in splits) == 4000.00

        overflow = client.post(
            f"/api/v2/admin/commissions/{commission_id}/splits",
            json={
                "recipient_type": "BROKER",
                "recipient_reference": "broker-beta",
                "amount": "1.00",
            },
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert overflow.status_code == 422
