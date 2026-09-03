import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./test-moneybee-finance.db",
)
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models
from app.db import SessionLocal
from app.financial_models import JournalEntry, JournalPosting
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


def tenant_headers(
    organization_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    request_id = str(uuid.uuid4())
    headers = {
        "X-Organization-ID": str(organization_id),
        "X-Request-ID": request_id,
        "X-Correlation-ID": f"correlation-{request_id}",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


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
        headers=tenant_headers(organization_id),
        json={
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
        headers=tenant_headers(organization_id),
        json={
            "name": f"period-{uuid.uuid4().hex[:8]}",
            "starts_at": (now - timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=30)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response


def journal_payload(
    cash_id: str,
    revenue_id: str,
    now: datetime,
    debit: str = "1250.00",
    credit: str = "1250.00",
    description: str = "Record test revenue",
):
    return {
        "source_type": "TEST",
        "source_id": "funding-test-1",
        "description": description,
        "currency": "USD",
        "effective_at": now.isoformat(),
        "postings": [
            {"account_id": cash_id, "side": "DEBIT", "amount": debit},
            {"account_id": revenue_id, "side": "CREDIT", "amount": credit},
        ],
    }


async def finance_evidence(entry_id: str) -> dict[str, int]:
    async with SessionLocal() as db:
        journal_count = int(
            await db.scalar(
                select(func.count(JournalEntry.id)).where(
                    JournalEntry.id == uuid.UUID(entry_id)
                )
            )
            or 0
        )
        posting_count = int(
            await db.scalar(
                select(func.count(JournalPosting.id)).where(
                    JournalPosting.journal_entry_id == uuid.UUID(entry_id)
                )
            )
            or 0
        )
        audit_count = int(
            await db.scalar(
                select(func.count(models.AuditEvent.id)).where(
                    models.AuditEvent.action == "FINANCE_JOURNAL_POSTED",
                    models.AuditEvent.resource_id == entry_id,
                )
            )
            or 0
        )
        outbox_count = int(
            await db.scalar(
                select(func.count(models.OutboxEvent.id)).where(
                    models.OutboxEvent.event_type == "FinanceJournalPosted",
                    models.OutboxEvent.aggregate_id == uuid.UUID(entry_id),
                )
            )
            or 0
        )
        return {
            "journal": journal_count,
            "postings": posting_count,
            "audit": audit_count,
            "outbox": outbox_count,
        }


async def journal_count_for_organization(organization_id: uuid.UUID) -> int:
    async with SessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(JournalEntry.id)).where(
                    JournalEntry.organization_id == organization_id
                )
            )
            or 0
        )


def test_financial_ledger_posts_one_atomic_transaction_and_replays_safely():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = create_account(client, organization_id, "1000", "Operating Cash", "ASSET")
        revenue = create_account(
            client,
            organization_id,
            "4000",
            "Funding Revenue",
            "REVENUE",
        )

        now = datetime.now(UTC)
        create_period(client, organization_id, now)
        key = str(uuid.uuid4())
        payload = journal_payload(cash.json()["id"], revenue.json()["id"], now)
        journal = client.post(
            "/api/v2/finance/journal-entries",
            headers=tenant_headers(organization_id, idempotency_key=key),
            json=payload,
        )
        assert journal.status_code == 201, journal.text
        assert journal.headers["X-Idempotent-Replay"] == "false"
        assert journal.json()["status"] == "POSTED"

        evidence = asyncio.run(finance_evidence(journal.json()["id"]))
        assert evidence == {
            "journal": 1,
            "postings": 2,
            "audit": 1,
            "outbox": 1,
        }

        replay = client.post(
            "/api/v2/finance/journal-entries",
            headers=tenant_headers(organization_id, idempotency_key=key),
            json=payload,
        )
        assert replay.status_code == 201, replay.text
        assert replay.headers["X-Idempotent-Replay"] == "true"
        assert replay.json()["id"] == journal.json()["id"]
        assert asyncio.run(finance_evidence(journal.json()["id"])) == evidence

        trial = client.get(
            "/api/v2/finance/trial-balance",
            headers=tenant_headers(organization_id),
            params={"currency": "USD"},
        )
        assert trial.status_code == 200, trial.text
        result = trial.json()
        assert result["balanced"] is True
        assert result["organization_id"] == str(organization_id)
        assert result["currency"] == "USD"
        assert result["debit_total"] == "1250.00"
        assert result["credit_total"] == "1250.00"
        assert len(result["accounts"]) == 2


def test_financial_ledger_rejects_same_key_with_different_economic_command():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = create_account(client, organization_id, "1010", "Cash", "ASSET")
        revenue = create_account(client, organization_id, "4010", "Revenue", "REVENUE")
        now = datetime.now(UTC)
        create_period(client, organization_id, now)
        key = str(uuid.uuid4())
        headers = tenant_headers(organization_id, idempotency_key=key)

        first = client.post(
            "/api/v2/finance/journal-entries",
            headers=headers,
            json=journal_payload(cash.json()["id"], revenue.json()["id"], now),
        )
        assert first.status_code == 201, first.text

        collision = client.post(
            "/api/v2/finance/journal-entries",
            headers=tenant_headers(organization_id, idempotency_key=key),
            json=journal_payload(
                cash.json()["id"],
                revenue.json()["id"],
                now,
                description="Different economic command",
            ),
        )
        assert collision.status_code == 409, collision.text
        assert collision.json()["code"] == "IDEMPOTENCY_CONFLICT"
        assert asyncio.run(journal_count_for_organization(organization_id)) == 1


def test_financial_ledger_rejects_unbalanced_journal_without_partial_rows():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = create_account(client, organization_id, "1020", "Cash", "ASSET")
        revenue = create_account(client, organization_id, "4020", "Revenue", "REVENUE")
        before = asyncio.run(journal_count_for_organization(organization_id))
        response = client.post(
            "/api/v2/finance/journal-entries",
            headers=tenant_headers(
                organization_id,
                idempotency_key=str(uuid.uuid4()),
            ),
            json=journal_payload(
                cash.json()["id"],
                revenue.json()["id"],
                datetime.now(UTC),
                debit="100.00",
                credit="99.00",
            ),
        )
        assert response.status_code == 422
        assert asyncio.run(journal_count_for_organization(organization_id)) == before


def test_financial_ledger_requires_open_accounting_period():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        cash = create_account(client, organization_id, "1030", "Cash", "ASSET")
        revenue = create_account(client, organization_id, "4030", "Revenue", "REVENUE")
        response = client.post(
            "/api/v2/finance/journal-entries",
            headers=tenant_headers(
                organization_id,
                idempotency_key=str(uuid.uuid4()),
            ),
            json=journal_payload(
                cash.json()["id"],
                revenue.json()["id"],
                datetime.now(UTC),
            ),
        )
        assert response.status_code == 409
        assert response.json()["code"] == "ACCOUNTING_PERIOD_REQUIRED"


def test_trial_balance_requires_currency_for_multi_currency_chart():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        create_account(client, organization_id, "1100", "USD Cash", "ASSET", "USD")
        create_account(client, organization_id, "1110", "EUR Cash", "ASSET", "EUR")

        ambiguous = client.get(
            "/api/v2/finance/trial-balance",
            headers=tenant_headers(organization_id),
        )
        assert ambiguous.status_code == 422
        assert ambiguous.json()["code"] == "CURRENCY_REQUIRED"

        usd = client.get(
            "/api/v2/finance/trial-balance",
            headers=tenant_headers(organization_id),
            params={"currency": "usd"},
        )
        assert usd.status_code == 200, usd.text
        assert usd.json()["currency"] == "USD"
        assert len(usd.json()["accounts"]) == 1


def test_finance_contract_uses_headers_not_query_or_body_for_tenant_and_replay():
    with TestClient(app) as client:
        organization_id = asyncio.run(create_organization())
        missing_context = client.get("/api/v2/finance/accounts")
        assert missing_context.status_code == 422
        assert missing_context.json()["code"] == "ORGANIZATION_REQUIRED"

        forbidden_body = client.post(
            "/api/v2/finance/accounts",
            headers=tenant_headers(organization_id),
            json={
                "organization_id": str(organization_id),
                "code": "1200",
                "name": "Invalid tenant body",
                "account_type": "ASSET",
            },
        )
        assert forbidden_body.status_code == 422

        unknown_query_is_ignored_by_fastapi = client.get(
            "/api/v2/finance/accounts",
            headers=tenant_headers(organization_id),
            params={"organization_id": str(uuid.uuid4())},
        )
        assert unknown_query_is_ignored_by_fastapi.status_code == 200

        cash = create_account(client, organization_id, "1210", "Cash", "ASSET")
        revenue = create_account(client, organization_id, "4210", "Revenue", "REVENUE")
        now = datetime.now(UTC)
        create_period(client, organization_id, now)
        missing_key = client.post(
            "/api/v2/finance/journal-entries",
            headers=tenant_headers(organization_id),
            json=journal_payload(cash.json()["id"], revenue.json()["id"], now),
        )
        assert missing_key.status_code == 422

        forbidden_key_body = client.post(
            "/api/v2/finance/journal-entries",
            headers=tenant_headers(
                organization_id,
                idempotency_key=str(uuid.uuid4()),
            ),
            json={
                **journal_payload(cash.json()["id"], revenue.json()["id"], now),
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert forbidden_key_body.status_code == 422


def test_finance_routes_are_v2_canonical_and_openapi_exposes_header_contract():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    assert "/api/v2/finance/accounts" in openapi["paths"]
    assert "/api/v2/finance/journal-entries" in openapi["paths"]
    assert "/api/v2/finance/trial-balance" in openapi["paths"]
    assert "/api/v1/finance/accounts" not in openapi["paths"]

    account_schema = openapi["components"]["schemas"]["LedgerAccountCreate"]
    journal_schema = openapi["components"]["schemas"]["JournalEntryCreate"]
    assert "organization_id" not in account_schema.get("properties", {})
    assert "organization_id" not in journal_schema.get("properties", {})
    assert "idempotency_key" not in journal_schema.get("properties", {})

    journal_parameters = openapi["paths"]["/api/v2/finance/journal-entries"]["post"][
        "parameters"
    ]
    key_parameter = next(
        parameter
        for parameter in journal_parameters
        if parameter["name"] == "Idempotency-Key"
    )
    assert key_parameter["in"] == "header"
    assert key_parameter["required"] is True
