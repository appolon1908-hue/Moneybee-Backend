import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.db import SessionLocal
from app.main import app


def _accept_an_offer_and_build_funding(client: TestClient) -> str:
    """Drives the real application -> match -> submission -> offer -> accept
    flow to reach a real Funding row, then returns its id. There is no
    endpoint yet to create a Funding directly (that engine isn't built),
    so accepted-offer is the only real path to one."""
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
            "business_name": "Commission Adjustment Test Co",
            "first_name": "Ada",
            "last_name": "Ledger",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550188",
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
            "legal_name": "Commission Adjustment Test Co LLC",
            "dba": "Commission Adjustment Test Co",
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
            "first_name": "Ada",
            "last_name": "Ledger",
            "ownership_percent": 100,
            "title": "Owner",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550188",
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
    submission_id = client.post(
        f"/api/v2/admin/applications/{application_id}/prepare-matched-submissions"
    ).json()[0]["id"]
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
    acknowledged = client.post(
        f"/api/v2/offers/{offer_id}/commercial-financing-disclosure/acknowledge"
    )
    assert acknowledged.status_code == 200
    accepted = client.post(
        f"/api/v2/offers/{offer_id}/accept",
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert accepted.status_code == 200

    funding = client.get(f"/api/v2/applications/{application_id}/funding")
    assert funding.status_code == 200
    return funding.json()["id"]


async def _create_commission(funding_id: str) -> str:
    async with SessionLocal() as db:
        commission = models.Commission(
            funding_id=uuid.UUID(funding_id),
            expected_amount="1500.00",
            status="EXPECTED",
        )
        db.add(commission)
        await db.commit()
        await db.refresh(commission)
        return str(commission.id)


async def test_commission_adjustment_is_idempotent_and_detects_payload_conflicts():
    with TestClient(app) as client:
        funding_id = _accept_an_offer_and_build_funding(client)
        commission_id = await _create_commission(funding_id)

        key = uuid.uuid4().hex
        payload = {
            "adjustment_type": "CLAWBACK",
            "amount": "-150.00",
            "reason": "Early repayment clawback per program terms.",
        }

        first = client.post(
            f"/api/v2/admin/commissions/{commission_id}/adjustments",
            json=payload,
            headers={"Idempotency-Key": key},
        )
        assert first.status_code == 201
        adjustment_id = first.json()["id"]

        replay = client.post(
            f"/api/v2/admin/commissions/{commission_id}/adjustments",
            json=payload,
            headers={"Idempotency-Key": key},
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == adjustment_id

        conflict = client.post(
            f"/api/v2/admin/commissions/{commission_id}/adjustments",
            json={**payload, "amount": "-999.00"},
            headers={"Idempotency-Key": key},
        )
        assert conflict.status_code == 409

        different_key = client.post(
            f"/api/v2/admin/commissions/{commission_id}/adjustments",
            json=payload,
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert different_key.status_code == 201
        assert different_key.json()["id"] != adjustment_id

        async with SessionLocal() as db:
            count = len(
                (
                    await db.scalars(
                        select(models.CommissionAdjustment).where(
                            models.CommissionAdjustment.commission_id == uuid.UUID(commission_id)
                        )
                    )
                ).all()
            )
        assert count == 2
