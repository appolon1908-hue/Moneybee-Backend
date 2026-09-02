import os
import uuid
from datetime import UTC, datetime, timedelta

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models, worker
from app.db import SessionLocal
from app.main import app


async def _seed_funded_funding(*, days_since_funded: int) -> tuple[str, str]:
    """Directly seeds an application + funded Funding old enough (or not)
    to test renewal eligibility, without driving the whole marketplace
    flow - the renewal engine only cares about Funding.status/
    funding_confirmed_at, not how it got there."""
    unique = uuid.uuid4().hex
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Rene",
            last_name="Newal",
            email=f"{unique}@example.com",
            phone="+15555550155",
            business_name="Renewal Engine Test Co",
            funding_amount=50000,
            use_of_funds="WORKING_CAPITAL",
            time_in_business_months=24,
            monthly_revenue=50000,
            postal_code="33101",
        )
        db.add(lead)
        await db.flush()
        application = models.Application(
            lead_id=lead.id,
            requested_amount=50000,
            monthly_revenue=50000,
            time_in_business_months=24,
        )
        db.add(application)
        await db.flush()
        offer = models.Offer(
            application_id=application.id,
            lender_id=uuid.uuid4(),
            product_type="WORKING_CAPITAL",
            amount=50000,
            term_months=12,
            payment_frequency="MONTHLY",
            payment_amount=5000,
            status="ACCEPTED",
        )
        db.add(offer)
        await db.flush()
        confirmed_at = datetime.now(UTC) - timedelta(days=days_since_funded)
        funding = models.Funding(
            application_id=application.id,
            offer_id=offer.id,
            status="FUNDED",
            approved_amount=50000,
            funded_amount=50000,
            funding_confirmed_at=confirmed_at,
        )
        db.add(funding)
        await db.commit()
        await db.refresh(funding)
        return str(application.id), str(funding.id)


async def test_evaluate_renewal_eligibility_creates_opportunity_past_the_window():
    with TestClient(app):
        application_id, funding_id = await _seed_funded_funding(days_since_funded=120)

        created = await worker.evaluate_pending_renewals()
        assert funding_id not in created  # created holds opportunity ids, not funding ids

        async with SessionLocal() as db:
            opportunity = await db.scalar(
                select(models.RenewalOpportunity).where(
                    models.RenewalOpportunity.original_funding_id == uuid.UUID(funding_id)
                )
            )
            assert opportunity is not None
            assert opportunity.eligibility_status == "ELIGIBLE"
            assert opportunity.status == "PENDING"
            assert opportunity.estimated_amount == 50000

        # Running it again must not create a second opportunity for the same funding.
        second_pass = await worker.evaluate_pending_renewals()
        assert second_pass == []


async def test_evaluate_renewal_eligibility_skips_recently_funded():
    with TestClient(app):
        application_id, funding_id = await _seed_funded_funding(days_since_funded=10)

        await worker.evaluate_pending_renewals()

        async with SessionLocal() as db:
            opportunity = await db.scalar(
                select(models.RenewalOpportunity).where(
                    models.RenewalOpportunity.original_funding_id == uuid.UUID(funding_id)
                )
            )
            assert opportunity is None


async def test_renewal_status_endpoint_is_idempotent_and_validates_transitions():
    with TestClient(app) as client:
        application_id, funding_id = await _seed_funded_funding(days_since_funded=120)
        await worker.evaluate_pending_renewals()

        async with SessionLocal() as db:
            opportunity = await db.scalar(
                select(models.RenewalOpportunity).where(
                    models.RenewalOpportunity.original_funding_id == uuid.UUID(funding_id)
                )
            )
            renewal_id = str(opportunity.id)

        readback = client.get(f"/api/v2/applications/{application_id}/renewal-opportunities")
        assert readback.status_code == 200
        assert readback.json()[0]["id"] == renewal_id

        key = uuid.uuid4().hex
        contacted = client.post(
            f"/api/v2/admin/renewal-opportunities/{renewal_id}/status",
            json={"status": "CONTACTED"},
            headers={"Idempotency-Key": key},
        )
        assert contacted.status_code == 200
        assert contacted.json()["status"] == "CONTACTED"

        replay = client.post(
            f"/api/v2/admin/renewal-opportunities/{renewal_id}/status",
            json={"status": "CONTACTED"},
            headers={"Idempotency-Key": key},
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "CONTACTED"

        converted = client.post(
            f"/api/v2/admin/renewal-opportunities/{renewal_id}/status",
            json={"status": "CONVERTED"},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert converted.status_code == 200
        assert converted.json()["status"] == "CONVERTED"

        # CONVERTED is terminal - a genuinely different next state 409s.
        invalid = client.post(
            f"/api/v2/admin/renewal-opportunities/{renewal_id}/status",
            json={"status": "CONTACTED"},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert invalid.status_code == 409
        assert invalid.json()["code"] == "INVALID_RENEWAL_STATUS_TRANSITION"
