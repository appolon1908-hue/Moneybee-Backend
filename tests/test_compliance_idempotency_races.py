import asyncio
import os
import uuid
from decimal import Decimal

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import compliance_models, models
from app.auth import Principal
from app.compliance_routes import record_tax_filing
from app.compliance_schemas import CommissionTaxRecordFilingInput
from app.db import SessionLocal, engine
from app.main import app


PRINCIPAL = Principal(
    user_id=uuid.UUID(int=0),
    issuer="test",
    subject="local-admin",
    organization_ids=(),
    active_organization_id=None,
    roles=frozenset({"MONEYBEE_ADMIN"}),
    permissions=frozenset({"*"}),
    membership_types=frozenset(),
    borrower_id=None,
    lender_id=None,
    is_active=True,
)


async def _seed_disclosure() -> tuple[str, str]:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Legacy",
            last_name="Disclosure",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550177",
            business_name="Legacy Disclosure LLC",
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
            requested_amount=Decimal("25000.00"),
            monthly_revenue=Decimal("30000.00"),
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
            disclosure_text="COMMERCIAL FINANCING DISCLOSURE - legacy route evidence",
        )
        db.add(disclosure)
        await db.commit()
        return str(offer.id), str(disclosure.id)


async def test_legacy_offer_acknowledgment_uses_audit_and_durable_idempotency():
    offer_id, disclosure_id = await _seed_disclosure()
    path = f"/api/v2/offers/{offer_id}/commercial-financing-disclosure/acknowledge"

    with TestClient(app) as client:
        first = client.post(path)
        replay = client.post(path)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["acknowledged_by"] == "local-admin"

    async with SessionLocal() as db:
        audit_count = int(
            await db.scalar(
                select(func.count())
                .select_from(models.AuditEvent)
                .where(
                    models.AuditEvent.action
                    == "COMMERCIAL_FINANCING_DISCLOSURE_ACKNOWLEDGED",
                    models.AuditEvent.resource_id == disclosure_id,
                )
            )
            or 0
        )
        idempotency_count = int(
            await db.scalar(
                select(func.count())
                .select_from(models.IdempotencyRecord)
                .where(
                    models.IdempotencyRecord.actor_id == "local-admin",
                    models.IdempotencyRecord.route == path.removeprefix("/api/v2"),
                    models.IdempotencyRecord.key
                    == f"offer-disclosure-ack:{offer_id}",
                )
            )
            or 0
        )
        assert audit_count == 1
        assert idempotency_count == 1


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL advisory-lock race test",
)
async def test_concurrent_tax_filing_same_key_replays_instead_of_raising_integrity_error():
    async with SessionLocal() as db:
        record = compliance_models.CommissionTaxRecord(
            recipient_type="BROKER",
            recipient_reference=f"broker-{uuid.uuid4().hex}",
            recipient_name="Race Test Broker",
            tax_year=2030,
            total_amount=Decimal("900.00"),
            commission_count=2,
            requires_1099=True,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        record_id = record.id

    key = f"filing-race-{uuid.uuid4().hex}"
    payload = CommissionTaxRecordFilingInput(
        filing_reference="IRS-RACE-2030-0001"
    )

    async def invoke():
        async with SessionLocal() as db:
            return await record_tax_filing(
                record_id,
                payload,
                db,
                PRINCIPAL,
                key,
            )

    first, second = await asyncio.gather(invoke(), invoke())

    def normalized(value):
        return value if isinstance(value, dict) else value.model_dump(mode="json")

    assert normalized(first) == normalized(second)
    async with SessionLocal() as db:
        idempotency_count = int(
            await db.scalar(
                select(func.count())
                .select_from(models.IdempotencyRecord)
                .where(
                    models.IdempotencyRecord.actor_id == PRINCIPAL.subject,
                    models.IdempotencyRecord.route
                    == f"/admin/compliance/commission-tax-records/{record_id}/filing",
                    models.IdempotencyRecord.key == key,
                )
            )
            or 0
        )
        audit_count = int(
            await db.scalar(
                select(func.count())
                .select_from(models.AuditEvent)
                .where(
                    models.AuditEvent.action == "COMMISSION_TAX_RECORD_FILED",
                    models.AuditEvent.resource_id == str(record_id),
                )
            )
            or 0
        )
        assert idempotency_count == 1
        assert audit_count == 1
