import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee-finance.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")

from fastapi.testclient import TestClient

from app.auth import Principal
from app.db import SessionLocal
from app.financial_service import resolve_organization
from app.identity_models import Organization
from app.main import app


async def create_organization() -> uuid.UUID:
    async with SessionLocal() as db:
        organization = Organization(
            name=f"MoneyBee Finance {uuid.uuid4().hex[:8]}",
            organization_type="MONEYBEE",
        )
        db.add(organization)
        await db.commit()
        await db.refresh(organization)
        return organization.id


def create_account(
    client: TestClient,
    organization_id: uuid.UUID,
    code: str,
    name: str,
    account_type: str,
    currency: str = "USD",
):
    response = client.post(
        "/api/v2/finance/accounts",
        json={
            "organization_id": str(organization_id),
            "code": code,
            "name": name,
            "account_type": account_type,
            "currency": currency,
        },
    )
    assert response.status_code == 201, response.text
    return response


def create_period(client: TestClient, organization_id: uuid.UUID, now: datetime):
    response = client.post(
        "/api/v2/finance/periods",
        json={
            "organization_id": str(organization_id),
            "name": f"period-{uuid.uuid4().hex[:8]}",
            "starts_at": (now - timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=30)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response


def journal_payload(
    organization_id: uuid.UUID,
    cash_id: str,
    revenue_id: str,
    now: datetime,
    idempotency_key: str,
    debit: str = "1250.00",
    credit: str = "1250.00",
):
    return {
        "organization_id": str(organization_id),
        "idempotency_key": idempotency_key,
        "source_type": "TEST",
        "source_id": "funding-test-1",
        "description": "Record test revenue",
        "currency": "USD",
        "effective_at": now.isoformat(),
        "postings": [
            {"account_id": cash_id, "side": "DEBIT", "amount": debit},
            {"account_id": revenue_id, "side": "CREDIT", "amount": credit},
        ],
    }


def test_financial_ledger_posts_balanced_journal_and_trial_balance():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = create_account(client, organization_id, "1000", "Operating Cash", "ASSET")
        revenue = create_account(client, organization_id, "4000", "Funding Revenue", "REVENUE")

        now = datetime.now(UTC)
        create_period(client, organization_id, now)
        key = str(uuid.uuid4())
        payload = journal_payload(
            organization_id,
            cash.json()["id"],
            revenue.json()["id"],
            now,
            key,
        )
        journal = client.post(
            "/api/v2/finance/journal-entries",
            headers={"Idempotency-Key": key},
            json=payload,
        )
        assert journal.status_code == 201, journal.text
        assert journal.json()["status"] == "POSTED"

        replay = client.post(
            "/api/v2/finance/journal-entries",
            headers={"Idempotency-Key": key},
            json=payload,
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["id"] == journal.json()["id"]

        trial = client.get(
            "/api/v2/finance/trial-balance",
            params={"organization_id": str(organization_id), "currency": "USD"},
        )
        assert trial.status_code == 200, trial.text
        result = trial.json()
        assert result["balanced"] is True
        assert result["currency"] == "USD"
        assert result["debit_total"] == "1250.00"
        assert result["credit_total"] == "1250.00"
        assert len(result["accounts"]) == 2


def test_financial_ledger_rejects_unbalanced_journal():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = create_account(client, organization_id, "1010", "Cash", "ASSET")
        revenue = create_account(client, organization_id, "4010", "Revenue", "REVENUE")
        key = str(uuid.uuid4())
        response = client.post(
            "/api/v2/finance/journal-entries",
            headers={"Idempotency-Key": key},
            json=journal_payload(
                organization_id,
                cash.json()["id"],
                revenue.json()["id"],
                datetime.now(UTC),
                key,
                debit="100.00",
                credit="99.00",
            ),
        )
        assert response.status_code == 422


def test_financial_ledger_requires_open_accounting_period():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = create_account(client, organization_id, "1020", "Cash", "ASSET")
        revenue = create_account(client, organization_id, "4020", "Revenue", "REVENUE")
        key = str(uuid.uuid4())
        response = client.post(
            "/api/v2/finance/journal-entries",
            headers={"Idempotency-Key": key},
            json=journal_payload(
                organization_id,
                cash.json()["id"],
                revenue.json()["id"],
                datetime.now(UTC),
                key,
            ),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "ACCOUNTING_PERIOD_REQUIRED"


def test_financial_ledger_rejects_mismatched_idempotency_keys():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = create_account(client, organization_id, "1030", "Cash", "ASSET")
        revenue = create_account(client, organization_id, "4030", "Revenue", "REVENUE")
        now = datetime.now(UTC)
        create_period(client, organization_id, now)
        body_key = str(uuid.uuid4())
        response = client.post(
            "/api/v2/finance/journal-entries",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json=journal_payload(
                organization_id,
                cash.json()["id"],
                revenue.json()["id"],
                now,
                body_key,
            ),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_MISMATCH"


def test_trial_balance_requires_currency_for_multi_currency_chart():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        create_account(client, organization_id, "1100", "USD Cash", "ASSET", "USD")
        create_account(client, organization_id, "1110", "EUR Cash", "ASSET", "EUR")

        ambiguous = client.get(
            "/api/v2/finance/trial-balance",
            params={"organization_id": str(organization_id)},
        )
        assert ambiguous.status_code == 422
        assert ambiguous.json()["detail"]["code"] == "CURRENCY_REQUIRED"

        usd = client.get(
            "/api/v2/finance/trial-balance",
            params={"organization_id": str(organization_id), "currency": "usd"},
        )
        assert usd.status_code == 200, usd.text
        assert usd.json()["currency"] == "USD"
        assert len(usd.json()["accounts"]) == 1


def test_selected_organization_cannot_be_overridden_by_payload_or_query():
    selected = uuid.uuid4()
    other = uuid.uuid4()
    principal = Principal(
        user_id=uuid.uuid4(),
        issuer="test",
        subject="subject",
        organization_ids=(selected, other),
        active_organization_id=selected,
        roles=frozenset(),
        permissions=frozenset({"finance.read"}),
        membership_types=frozenset({"MONEYBEE"}),
        borrower_id=None,
        lender_id=None,
        is_active=True,
    )

    assert resolve_organization(principal, selected) == selected
    try:
        resolve_organization(principal, other)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
        assert exc.detail["code"] == "ORGANIZATION_CONTEXT_MISMATCH"
    else:
        raise AssertionError("cross-context organization override should fail")


def test_finance_routes_are_v2_canonical_and_v1_hidden():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    assert "/api/v2/finance/accounts" in openapi["paths"]
    assert "/api/v2/finance/journal-entries" in openapi["paths"]
    assert "/api/v2/finance/trial-balance" in openapi["paths"]
    assert "/api/v1/finance/accounts" not in openapi["paths"]
