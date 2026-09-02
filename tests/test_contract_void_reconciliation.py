import os
import uuid
from decimal import Decimal

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.db import SessionLocal
from app.integration_models import OperationalException
from app.integrations.base import ProviderError
from app.main import app


async def _seed_sent_contract() -> str:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Void",
            last_name="Reconciliation",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550145",
            business_name="Void Reconciliation LLC",
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
            status="ACCEPTED",
        )
        db.add(offer)
        await db.flush()
        contract = models.Contract(
            application_id=application.id,
            offer_id=offer.id,
            template_version="test-v1",
            provider="docusign",
            external_envelope_id=f"envelope-{uuid.uuid4().hex}",
            status="SENT",
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return str(contract.id)


async def test_void_response_loss_is_reconciled_before_local_transition(monkeypatch):
    contract_id = await _seed_sent_contract()

    class AcceptedButResponseLost:
        void_calls = 0
        status_calls = 0

        async def void_envelope(self, **kwargs):
            self.void_calls += 1
            raise ProviderError("docusign", "simulated lost response")

        async def envelope_status(self, **kwargs):
            self.status_calls += 1
            return {"status": "voided"}

    fake = AcceptedButResponseLost()
    monkeypatch.setattr("app.admin_routes.esign_adapter", lambda: fake)

    with TestClient(app) as client:
        response = client.post(
            f"/api/v2/admin/contracts/{contract_id}/void",
            headers={"Idempotency-Key": uuid.uuid4().hex},
            json={"reason": "Offer superseded."},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "VOIDED"
    assert fake.void_calls == 1
    assert fake.status_calls == 1

    async with SessionLocal() as db:
        contract = await db.get(models.Contract, uuid.UUID(contract_id))
        assert contract is not None
        assert contract.status == "VOIDED"
        assert contract.provider_attempt_count == 1
        assert contract.provider_last_error is None
        exception = await db.scalar(
            select(OperationalException).where(
                OperationalException.fingerprint
                == f"CONTRACT_VOID_OUTCOME_UNKNOWN:{contract_id}"
            )
        )
        assert exception is None


async def test_unknown_void_blocks_repeat_until_readback_confirms(monkeypatch):
    contract_id = await _seed_sent_contract()

    class UnknownOutcome:
        void_calls = 0
        status_calls = 0

        async def void_envelope(self, **kwargs):
            self.void_calls += 1
            raise ProviderError("docusign", "simulated timeout")

        async def envelope_status(self, **kwargs):
            self.status_calls += 1
            raise ProviderError("docusign", "status unavailable")

    first_fake = UnknownOutcome()
    monkeypatch.setattr("app.admin_routes.esign_adapter", lambda: first_fake)

    with TestClient(app) as client:
        first = client.post(
            f"/api/v2/admin/contracts/{contract_id}/void",
            headers={"Idempotency-Key": uuid.uuid4().hex},
            json={"reason": "Offer superseded."},
        )

    assert first.status_code == 503
    assert first.json()["code"] == "CONTRACT_VOID_RECONCILIATION_REQUIRED"
    assert first_fake.void_calls == 1
    assert first_fake.status_calls == 1

    async with SessionLocal() as db:
        contract = await db.get(models.Contract, uuid.UUID(contract_id))
        assert contract is not None
        assert contract.status == "SENT"
        assert contract.provider_terminal_at is not None
        exception = await db.scalar(
            select(OperationalException).where(
                OperationalException.fingerprint
                == f"CONTRACT_VOID_OUTCOME_UNKNOWN:{contract_id}"
            )
        )
        assert exception is not None
        assert exception.status == "OPEN"

    class ReadbackOnly:
        void_calls = 0
        status_calls = 0

        async def void_envelope(self, **kwargs):
            self.void_calls += 1
            raise AssertionError("An unknown void operation must never be repeated")

        async def envelope_status(self, **kwargs):
            self.status_calls += 1
            return {"status": "voided"}

    second_fake = ReadbackOnly()
    monkeypatch.setattr("app.admin_routes.esign_adapter", lambda: second_fake)

    with TestClient(app) as client:
        reconciled = client.post(
            f"/api/v2/admin/contracts/{contract_id}/void",
            headers={"Idempotency-Key": uuid.uuid4().hex},
            json={"reason": "Offer superseded."},
        )

    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "VOIDED"
    assert second_fake.void_calls == 0
    assert second_fake.status_calls == 1

    async with SessionLocal() as db:
        exception = await db.scalar(
            select(OperationalException).where(
                OperationalException.fingerprint
                == f"CONTRACT_VOID_OUTCOME_UNKNOWN:{contract_id}"
            )
        )
        assert exception is not None
        assert exception.status == "RESOLVED"
        assert exception.resolved_at is not None
