import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee-finance.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.identity_models import Organization
from app.main import app


async def create_organization() -> uuid.UUID:
    async with SessionLocal() as db:
        organization = Organization(name=f"MoneyBee Finance {uuid.uuid4().hex[:8]}", organization_type="MONEYBEE")
        db.add(organization)
        await db.commit()
        await db.refresh(organization)
        return organization.id


def test_financial_ledger_posts_balanced_journal_and_trial_balance():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = client.post(
            "/api/v2/finance/accounts",
            json={
                "organization_id": str(organization_id),
                "code": "1000",
                "name": "Operating Cash",
                "account_type": "ASSET",
                "currency": "USD",
            },
        )
        revenue = client.post(
            "/api/v2/finance/accounts",
            json={
                "organization_id": str(organization_id),
                "code": "4000",
                "name": "Funding Revenue",
                "account_type": "REVENUE",
                "currency": "USD",
            },
        )
        assert cash.status_code == 201, cash.text
        assert revenue.status_code == 201, revenue.text

        now = datetime.now(UTC)
        period = client.post(
            "/api/v2/finance/periods",
            json={
                "organization_id": str(organization_id),
                "name": f"period-{uuid.uuid4().hex[:8]}",
                "starts_at": (now - timedelta(days=1)).isoformat(),
                "ends_at": (now + timedelta(days=30)).isoformat(),
            },
        )
        assert period.status_code == 201, period.text

        journal = client.post(
            "/api/v2/finance/journal-entries",
            json={
                "organization_id": str(organization_id),
                "idempotency_key": str(uuid.uuid4()),
                "source_type": "TEST",
                "source_id": "funding-test-1",
                "description": "Record test revenue",
                "currency": "USD",
                "effective_at": now.isoformat(),
                "postings": [
                    {"account_id": cash.json()["id"], "side": "DEBIT", "amount": "1250.00"},
                    {"account_id": revenue.json()["id"], "side": "CREDIT", "amount": "1250.00"},
                ],
            },
        )
        assert journal.status_code == 201, journal.text
        assert journal.json()["status"] == "POSTED"

        trial = client.get(
            "/api/v2/finance/trial-balance",
            params={"organization_id": str(organization_id)},
        )
        assert trial.status_code == 200, trial.text
        payload = trial.json()
        assert payload["balanced"] is True
        assert payload["debit_total"] == "1250.00"
        assert payload["credit_total"] == "1250.00"
        assert len(payload["accounts"]) == 2


def test_financial_ledger_rejects_unbalanced_journal():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = client.post(
            "/api/v2/finance/accounts",
            json={"organization_id": str(organization_id), "code": "1010", "name": "Cash", "account_type": "ASSET"},
        )
        revenue = client.post(
            "/api/v2/finance/accounts",
            json={"organization_id": str(organization_id), "code": "4010", "name": "Revenue", "account_type": "REVENUE"},
        )
        assert cash.status_code == 201
        assert revenue.status_code == 201

        response = client.post(
            "/api/v2/finance/journal-entries",
            json={
                "organization_id": str(organization_id),
                "idempotency_key": str(uuid.uuid4()),
                "source_type": "TEST",
                "description": "Unbalanced entry",
                "currency": "USD",
                "effective_at": datetime.now(UTC).isoformat(),
                "postings": [
                    {"account_id": cash.json()["id"], "side": "DEBIT", "amount": "100.00"},
                    {"account_id": revenue.json()["id"], "side": "CREDIT", "amount": "99.00"},
                ],
            },
        )
        assert response.status_code == 422


def test_finance_routes_are_v2_canonical_and_v1_hidden():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    assert "/api/v2/finance/accounts" in openapi["paths"]
    assert "/api/v2/finance/journal-entries" in openapi["paths"]
    assert "/api/v2/finance/trial-balance" in openapi["paths"]
    assert "/api/v1/finance/accounts" not in openapi["paths"]
