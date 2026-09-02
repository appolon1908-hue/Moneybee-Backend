import os
import uuid
from datetime import UTC, datetime

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.encryption import decrypt_secret
from app.main import app


async def _seed_commission_split(
    recipient_reference: str, amount: str, tax_year: int, recipient_type: str = "BROKER"
) -> None:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Tax",
            last_name="Record",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550111",
            business_name="1099 Test Co",
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
        funding = models.Funding(
            application_id=application.id,
            offer_id=offer.id,
            status="FUNDED",
            approved_amount=50000,
            funded_amount=50000,
        )
        db.add(funding)
        await db.flush()
        commission = models.Commission(
            funding_id=funding.id, expected_amount=4000, received_amount=4000, status="RECEIVED"
        )
        db.add(commission)
        await db.flush()
        split = models.CommissionSplit(
            commission_id=commission.id,
            recipient_type=recipient_type,
            recipient_reference=recipient_reference,
            amount=amount,
            status="PENDING",
        )
        db.add(split)
        await db.flush()
        # created_at defaults to "now" - backdate it into the target tax
        # year so this test doesn't depend on which year it happens to run in.
        split.created_at = datetime(tax_year, 6, 15, tzinfo=UTC)
        await db.commit()


async def test_generate_commission_tax_records_aggregates_by_recipient_and_applies_the_1099_threshold():
    tax_year = 2026
    ref_over_threshold = f"broker-{uuid.uuid4().hex}"
    ref_under_threshold = f"broker-{uuid.uuid4().hex}"

    with TestClient(app) as client:
        await _seed_commission_split(ref_over_threshold, "750.00", tax_year)
        await _seed_commission_split(ref_over_threshold, "250.00", tax_year)
        await _seed_commission_split(ref_under_threshold, "300.00", tax_year)

        response = client.post(
            "/api/v2/admin/commission-tax-records/generate",
            params={"tax_year": tax_year},
        )
        assert response.status_code == 200
        records = {row["recipient_reference"]: row for row in response.json()}

        assert records[ref_over_threshold]["total_amount"] == "1000.00"
        assert records[ref_over_threshold]["commission_count"] == 2
        assert records[ref_over_threshold]["requires_1099"] is True

        assert records[ref_under_threshold]["total_amount"] == "300.00"
        assert records[ref_under_threshold]["requires_1099"] is False

        listed = client.get(
            "/api/v2/admin/commission-tax-records", params={"tax_year": tax_year}
        )
        assert listed.status_code == 200
        assert {row["recipient_reference"] for row in listed.json()} >= {
            ref_over_threshold,
            ref_under_threshold,
        }


async def test_tax_records_keep_recipient_types_as_distinct_persisted_identities():
    tax_year = 2029
    reference = f"shared-{uuid.uuid4().hex}"
    with TestClient(app) as client:
        await _seed_commission_split(reference, "400.00", tax_year, "BROKER")
        await _seed_commission_split(reference, "700.00", tax_year, "HOUSE")
        response = client.post(
            "/api/v2/admin/commission-tax-records/generate", params={"tax_year": tax_year}
        )
        records = [row for row in response.json() if row["recipient_reference"] == reference]
        assert {(row["recipient_type"], row["total_amount"]) for row in records} == {
            ("BROKER", "400.00"), ("HOUSE", "700.00")
        }


async def test_regenerating_commission_tax_records_replaces_rather_than_accumulates():
    tax_year = 2027
    recipient_reference = f"broker-{uuid.uuid4().hex}"

    with TestClient(app) as client:
        await _seed_commission_split(recipient_reference, "700.00", tax_year)

        first = client.post(
            "/api/v2/admin/commission-tax-records/generate", params={"tax_year": tax_year}
        )
        first_total = next(
            row["total_amount"]
            for row in first.json()
            if row["recipient_reference"] == recipient_reference
        )
        assert first_total == "700.00"

        # A second real split for the same recipient, then regenerate -
        # the record should reflect the new true total, not double-count.
        await _seed_commission_split(recipient_reference, "150.00", tax_year)
        second = client.post(
            "/api/v2/admin/commission-tax-records/generate", params={"tax_year": tax_year}
        )
        second_total = next(
            row["total_amount"]
            for row in second.json()
            if row["recipient_reference"] == recipient_reference
        )
        assert second_total == "850.00"

        listed = client.get(
            "/api/v2/admin/commission-tax-records", params={"tax_year": tax_year}
        )
        matching = [
            row for row in listed.json() if row["recipient_reference"] == recipient_reference
        ]
        assert len(matching) == 1


async def test_setting_a_recipient_tin_stores_it_encrypted():
    tax_year = 2028
    recipient_reference = f"broker-{uuid.uuid4().hex}"

    with TestClient(app) as client:
        await _seed_commission_split(recipient_reference, "900.00", tax_year)

        generated = client.post(
            "/api/v2/admin/commission-tax-records/generate", params={"tax_year": tax_year}
        )
        record_id = next(
            row["id"]
            for row in generated.json()
            if row["recipient_reference"] == recipient_reference
        )

        updated = client.patch(
            f"/api/v2/admin/commission-tax-records/{record_id}/tin",
            json={"recipient_name": "Ralph Broker", "tin": "12-3456789"},
        )
        assert updated.status_code == 200
        assert updated.json()["recipient_name"] == "Ralph Broker"
        # The TIN itself is never returned in the clear.
        assert "tin" not in updated.json()

    async with SessionLocal() as db:
        from app import compliance_models

        stored = await db.get(compliance_models.CommissionTaxRecord, uuid.UUID(record_id))
        assert stored.tin_ciphertext is not None
        assert stored.tin_ciphertext != "12-3456789"
        assert decrypt_secret(stored.tin_ciphertext) == "12-3456789"
