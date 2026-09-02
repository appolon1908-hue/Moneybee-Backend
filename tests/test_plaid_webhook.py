import json
import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.config import settings
from app.db import SessionLocal
from app.integrations.plaid import PlaidAdapter
from app.main import app


async def _set_bank_live_connection_capability(enabled: bool) -> None:
    """Configure the single-database capability row for this test environment.

    Capability keys are globally unique in the current schema even though
    runtime lookups are environment-scoped. Migrated PostgreSQL test databases
    therefore already contain the production-seeded row, while auto-created
    SQLite databases do not. Rebinding that one row to the active test
    environment avoids inventing a duplicate key and keeps provider readiness
    outside these webhook unit tests.
    """
    async with SessionLocal() as db:
        existing = await db.scalar(
            select(models.CapabilityFlag).where(
                models.CapabilityFlag.key == "bank.live_connection"
            )
        )
        if existing is not None:
            existing.environment = settings.app_env
            existing.enabled = enabled
            existing.provider = None
        else:
            db.add(
                models.CapabilityFlag(
                    key="bank.live_connection",
                    environment=settings.app_env,
                    enabled=enabled,
                    provider=None,
                )
            )
        await db.commit()


async def _seed_bank_connection(item_id: str) -> str:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Bea",
            last_name="Nkaccount",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550166",
            business_name="Plaid Webhook Test Co",
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
        connection = models.BankConnection(
            application_id=application.id,
            provider="plaid",
            provider_reference=item_id,
            status="CONNECTED",
        )
        db.add(connection)
        await db.commit()
        await db.refresh(connection)
        return str(connection.id)


def _plaid_payload(item_id: str, webhook_type: str, webhook_code: str) -> bytes:
    return json.dumps(
        {"webhook_type": webhook_type, "webhook_code": webhook_code, "item_id": item_id}
    ).encode()


async def test_plaid_webhook_rejects_an_invalid_signature(monkeypatch):
    async def deny(self, body, signed_token):
        return False

    monkeypatch.setattr(PlaidAdapter, "verify_webhook", deny)

    with TestClient(app) as client:
        await _set_bank_live_connection_capability(True)
        try:
            response = client.post(
                "/api/v2/webhooks/plaid",
                content=_plaid_payload("item-1", "ITEM", "ERROR"),
                headers={"Plaid-Verification": "not-a-real-token"},
            )
        finally:
            # Other tests (test_provider_adapters.py's fail-closed test in
            # particular) rely on this capability being off by default in
            # the shared test database, regardless of collection order.
            await _set_bank_live_connection_capability(False)

    assert response.status_code == 401


async def test_plaid_item_error_marks_the_matching_connection_reauth_required(monkeypatch):
    async def accept(self, body, signed_token):
        return True

    monkeypatch.setattr(PlaidAdapter, "verify_webhook", accept)
    item_id = f"item-{uuid.uuid4().hex}"

    with TestClient(app) as client:
        connection_id = await _seed_bank_connection(item_id)
        await _set_bank_live_connection_capability(True)
        try:
            response = client.post(
                "/api/v2/webhooks/plaid",
                content=_plaid_payload(item_id, "ITEM", "ERROR"),
                headers={"Plaid-Verification": "signed-token"},
            )
        finally:
            await _set_bank_live_connection_capability(False)

        assert response.status_code == 200
        body = response.json()
        assert body["received"] is True
        assert body["duplicate"] is False
        assert body["connection_status"] == "REAUTH_REQUIRED"

        async with SessionLocal() as db:
            connection = await db.get(models.BankConnection, uuid.UUID(connection_id))
            assert connection.status == "REAUTH_REQUIRED"


async def test_plaid_login_repaired_recovers_the_connection(monkeypatch):
    async def accept(self, body, signed_token):
        return True

    monkeypatch.setattr(PlaidAdapter, "verify_webhook", accept)
    item_id = f"item-{uuid.uuid4().hex}"

    with TestClient(app) as client:
        connection_id = await _seed_bank_connection(item_id)
        async with SessionLocal() as db:
            connection = await db.get(models.BankConnection, uuid.UUID(connection_id))
            connection.status = "REAUTH_REQUIRED"
            await db.commit()

        await _set_bank_live_connection_capability(True)
        try:
            response = client.post(
                "/api/v2/webhooks/plaid",
                content=_plaid_payload(item_id, "ITEM", "LOGIN_REPAIRED"),
                headers={"Plaid-Verification": "signed-token"},
            )
        finally:
            await _set_bank_live_connection_capability(False)

        assert response.status_code == 200
        assert response.json()["connection_status"] == "CONNECTED"

        async with SessionLocal() as db:
            connection = await db.get(models.BankConnection, uuid.UUID(connection_id))
            assert connection.status == "CONNECTED"


async def test_plaid_webhook_is_idempotent_for_a_replayed_event(monkeypatch):
    async def accept(self, body, signed_token):
        return True

    monkeypatch.setattr(PlaidAdapter, "verify_webhook", accept)
    item_id = f"item-{uuid.uuid4().hex}"
    payload = _plaid_payload(item_id, "TRANSACTIONS", "SYNC_UPDATES_AVAILABLE")

    with TestClient(app) as client:
        await _set_bank_live_connection_capability(True)
        try:
            first = client.post(
                "/api/v2/webhooks/plaid",
                content=payload,
                headers={"Plaid-Verification": "signed-token"},
            )
            second = client.post(
                "/api/v2/webhooks/plaid",
                content=payload,
                headers={"Plaid-Verification": "signed-token"},
            )
        finally:
            await _set_bank_live_connection_capability(False)

    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
