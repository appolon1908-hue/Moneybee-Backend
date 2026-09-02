import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import compliance_models, models
from app.db import SessionLocal
from app.encryption import decrypt_secret
from app.main import app


async def _seed_disclosure() -> tuple[str, str, str]:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Casey",
            last_name="Compliance",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550101",
            business_name="Compliance API Test LLC",
            funding_amount=25000,
            use_of_funds="WORKING_CAPITAL",
            time_in_business_months=24,
            monthly_revenue=30000,
            postal_code="33101",
        )
        db.add(lead)
        await db.flush()
        application = models.Application(
            lead_id=lead.id,
            requested_amount=25000,
            monthly_revenue=30000,
            time_in_business_months=24,
        )
        db.add(application)
        await db.flush()
        offer = models.Offer(
            application_id=application.id,
            lender_id=uuid.uuid4(),
            product_type="WORKING_CAPITAL",
            amount=Decimal("25000.00"),
            term_months=12,
            payment_frequency="MONTHLY",
            payment_amount=Decimal("2300.00"),
            total_repayment=Decimal("27600.00"),
            status="AVAILABLE",
        )
        db.add(offer)
        await db.flush()
        disclosure = compliance_models.CommercialFinancingDisclosure(
            offer_id=offer.id,
            application_id=application.id,
            jurisdiction="FL",
            amount_financed=Decimal("25000.00"),
            finance_charge=Decimal("2600.00"),
            total_repayment_amount=Decimal("27600.00"),
            estimated_apr=Decimal("10.4000"),
            payment_amount=Decimal("2300.00"),
            payment_frequency="MONTHLY",
            term_months=12,
            prepayment_policy="No prepayment penalty.",
            disclosure_text="COMMERCIAL FINANCING DISCLOSURE - test evidence",
        )
        db.add(disclosure)
        await db.commit()
        return str(application.id), str(offer.id), str(disclosure.id)


async def _seed_tax_record() -> str:
    async with SessionLocal() as db:
        record = compliance_models.CommissionTaxRecord(
            recipient_type="BROKER",
            recipient_reference=f"broker-{uuid.uuid4().hex}",
            recipient_name=None,
            tax_year=2029,
            total_amount=Decimal("900.00"),
            commission_count=2,
            requires_1099=True,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return str(record.id)


def test_compliance_overview_and_pages_are_explicit_and_paginated():
    with TestClient(app) as client:
        overview = client.get("/api/v2/admin/compliance/overview")
        assert overview.status_code == 200
        assert set(overview.json()) == {
            "adverse_action_notices",
            "adverse_action_notices_pending_delivery",
            "commercial_financing_disclosures",
            "commercial_financing_disclosures_unacknowledged",
            "commission_tax_records",
            "commission_tax_records_requiring_1099",
            "commission_tax_records_missing_tin",
            "generated_at",
        }

        for path in (
            "/api/v2/admin/compliance/adverse-action-notices",
            "/api/v2/admin/compliance/commercial-financing-disclosures",
            "/api/v2/admin/compliance/commission-tax-records",
        ):
            response = client.get(path, params={"limit": 1, "offset": 0})
            assert response.status_code == 200
            body = response.json()
            assert set(body) == {"items", "total", "limit", "offset", "has_more"}
            assert body["limit"] == 1
            assert body["offset"] == 0
            assert body["total"] >= len(body["items"])

        invalid = client.get(
            "/api/v2/admin/compliance/commercial-financing-disclosures",
            params={"limit": 0},
        )
        assert invalid.status_code == 422
        assert invalid.headers["content-type"].startswith("application/problem+json")


async def test_borrower_can_read_and_idempotently_acknowledge_own_disclosure():
    key = f"disclosure-{uuid.uuid4().hex}"

    with TestClient(app) as client:
        application_id, offer_id, disclosure_id = await _seed_disclosure()
        read = client.get(
            f"/api/v2/borrower/offers/{offer_id}/commercial-financing-disclosure"
        )
        assert read.status_code == 200
        assert read.json()["application_id"] == application_id
        assert read.json()["acknowledged_at"] is None

        missing_key = client.post(
            f"/api/v2/borrower/offers/{offer_id}/commercial-financing-disclosure/acknowledge"
        )
        assert missing_key.status_code == 422

        first = client.post(
            f"/api/v2/borrower/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
            headers={"Idempotency-Key": key},
            json={"acknowledged_by": "spoofed-client-value"},
        )
        assert first.status_code == 200
        assert first.json()["acknowledged_at"] is not None
        assert first.json()["acknowledged_by"] == "local-admin"

        replay = client.post(
            f"/api/v2/borrower/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
            headers={"Idempotency-Key": key},
        )
        assert replay.status_code == 200
        assert replay.json() == first.json()

    async with SessionLocal() as db:
        disclosure = await db.get(
            compliance_models.CommercialFinancingDisclosure,
            uuid.UUID(disclosure_id),
        )
        assert disclosure is not None
        assert disclosure.acknowledged_by == "local-admin"
        audit = await db.scalar(
            select(models.AuditEvent).where(
                models.AuditEvent.action
                == "COMMERCIAL_FINANCING_DISCLOSURE_ACKNOWLEDGED",
                models.AuditEvent.resource_id == disclosure_id,
            )
        )
        assert audit is not None
        assert audit.actor_id == "local-admin"


async def test_tax_record_api_never_returns_tin_and_records_filing_evidence():
    with TestClient(app) as client:
        record_id = await _seed_tax_record()
        listed = client.get(
            "/api/v2/admin/compliance/commission-tax-records",
            params={"tax_year": 2029, "requires_1099": True, "tin_present": False},
        )
        assert listed.status_code == 200
        row = next(item for item in listed.json()["items"] if item["id"] == record_id)
        assert row["tin_present"] is False
        assert "tin" not in row
        assert "tin_ciphertext" not in row

        updated = client.patch(
            f"/api/v2/admin/compliance/commission-tax-records/{record_id}/tin",
            json={"recipient_name": "Casey Broker", "tin": "12-3456789"},
        )
        assert updated.status_code == 200
        assert updated.json()["recipient_name"] == "Casey Broker"
        assert updated.json()["tin_present"] is True
        assert "tin" not in updated.json()
        assert "tin_ciphertext" not in updated.json()

        filing_key = f"filing-{uuid.uuid4().hex}"
        filed = client.patch(
            f"/api/v2/admin/compliance/commission-tax-records/{record_id}/filing",
            headers={"Idempotency-Key": filing_key},
            json={"filing_reference": "IRS-TEST-2029-0001"},
        )
        assert filed.status_code == 200
        assert filed.json()["filed_at"] is not None
        assert filed.json()["filing_reference"] == "IRS-TEST-2029-0001"

        replay = client.patch(
            f"/api/v2/admin/compliance/commission-tax-records/{record_id}/filing",
            headers={"Idempotency-Key": filing_key},
            json={"filing_reference": "IRS-TEST-2029-0001"},
        )
        assert replay.status_code == 200
        assert replay.json() == filed.json()

        overwrite = client.patch(
            f"/api/v2/admin/compliance/commission-tax-records/{record_id}/filing",
            headers={"Idempotency-Key": f"filing-{uuid.uuid4().hex}"},
            json={"filing_reference": "DIFFERENT-REFERENCE"},
        )
        assert overwrite.status_code == 409
        assert overwrite.json()["code"] == "FILING_ALREADY_RECORDED"

    async with SessionLocal() as db:
        record = await db.get(
            compliance_models.CommissionTaxRecord,
            uuid.UUID(record_id),
        )
        assert record is not None
        assert record.tin_ciphertext is not None
        assert record.tin_ciphertext != "12-3456789"
        assert decrypt_secret(record.tin_ciphertext) == "12-3456789"
        assert record.filing_reference == "IRS-TEST-2029-0001"
