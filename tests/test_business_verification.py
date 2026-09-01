"""Business verification was a confirmed dead end: app/domain_logic.py's
create_requirement_snapshot has always queried for a Verification row
(verification_type="BUSINESS", status="VERIFIED") behind the
kyb.live_verification capability, but nothing anywhere ever wrote one -
no service function, no endpoint. This covers the new
domain_logic.run_business_verification() and the admin endpoints that
call it.
"""

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
from app.integrations.base import ProviderError
from app.integrations.middesk import MiddeskAdapter
from app.main import app


async def _set_kyb_capability(enabled: bool) -> None:
    async with SessionLocal() as db:
        existing = await db.scalar(
            select(models.CapabilityFlag).where(
                models.CapabilityFlag.key == "kyb.live_verification"
            )
        )
        if existing is not None:
            existing.environment = settings.app_env
            existing.enabled = enabled
            existing.provider = None
        else:
            db.add(
                models.CapabilityFlag(
                    key="kyb.live_verification",
                    environment=settings.app_env,
                    enabled=enabled,
                    provider=None,
                )
            )
        await db.commit()


def _prepare_application_with_business(client: TestClient) -> str:
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
            "business_name": "Verification Test Co",
            "first_name": "Val",
            "last_name": "Idation",
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
            "legal_name": "Verification Test Co LLC",
            "dba": "Verification Test Co",
            "entity_type": "LLC",
            "state_formed": "FL",
            "industry": "TRANSPORTATION",
            "website": "https://example.com",
            "address": {"city": "Miami", "state": "FL"},
        },
    )
    client.post(
        f"/api/v2/applications/{application_id}/owners",
        json={
            "first_name": "Val",
            "last_name": "Idation",
            "ownership_percent": 100,
            "title": "Owner",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550188",
            "address": {"city": "Miami", "state": "FL"},
        },
    )
    return application_id


def test_business_verification_fails_closed_without_the_capability():
    with TestClient(app) as client:
        application_id = _prepare_application_with_business(client)
        response = client.post(
            f"/api/v2/admin/applications/{application_id}/business-verifications"
        )
        assert response.status_code == 503


async def test_business_verification_runs_and_persists_the_result(monkeypatch):
    monkeypatch.setattr(settings, "kyb_provider", "middesk")
    monkeypatch.setattr(settings, "middesk_api_key", "test-key")

    async def fake_verify_business(self, payload: dict) -> dict:
        assert payload["business_name"] == "Verification Test Co LLC"
        assert payload["owners"] == [
            {"first_name": "Val", "last_name": "Idation", "title": "Owner"}
        ]
        return {
            "provider": "middesk",
            "provider_reference": "biz_123",
            "status": "VERIFIED",
            "normalized_result": {"provider_status": "approved", "risk_flags": []},
        }

    monkeypatch.setattr(MiddeskAdapter, "verify_business", fake_verify_business)

    with TestClient(app) as client:
        await _set_kyb_capability(True)
        application_id = _prepare_application_with_business(client)

        response = client.post(
            f"/api/v2/admin/applications/{application_id}/business-verifications"
        )
        assert response.status_code == 201
        body = response.json()
        assert body["verification_type"] == "BUSINESS"
        assert body["provider"] == "middesk"
        assert body["provider_reference"] == "biz_123"
        assert body["status"] == "VERIFIED"

        listed = client.get(f"/api/v2/admin/applications/{application_id}/verifications")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == body["id"]


async def test_rerunning_business_verification_updates_the_same_row(monkeypatch):
    monkeypatch.setattr(settings, "kyb_provider", "middesk")
    monkeypatch.setattr(settings, "middesk_api_key", "test-key")

    call_count = {"n": 0}

    async def fake_verify_business(self, payload: dict) -> dict:
        call_count["n"] += 1
        status = "PENDING" if call_count["n"] == 1 else "VERIFIED"
        return {
            "provider": "middesk",
            "provider_reference": "biz_456",
            "status": status,
            "normalized_result": {},
        }

    monkeypatch.setattr(MiddeskAdapter, "verify_business", fake_verify_business)

    with TestClient(app) as client:
        await _set_kyb_capability(True)
        application_id = _prepare_application_with_business(client)

        first = client.post(
            f"/api/v2/admin/applications/{application_id}/business-verifications"
        )
        second = client.post(
            f"/api/v2/admin/applications/{application_id}/business-verifications"
        )
        assert first.json()["status"] == "PENDING"
        assert second.json()["status"] == "VERIFIED"
        assert first.json()["id"] == second.json()["id"]

        listed = client.get(
            f"/api/v2/admin/applications/{application_id}/verifications"
        ).json()
        assert len(listed) == 1


async def test_business_verification_provider_failure_returns_502(monkeypatch):
    monkeypatch.setattr(settings, "kyb_provider", "middesk")
    monkeypatch.setattr(settings, "middesk_api_key", "test-key")

    async def failing_verify_business(self, payload: dict) -> dict:
        raise ProviderError("middesk", "Provider request failed", status_code=500)

    monkeypatch.setattr(MiddeskAdapter, "verify_business", failing_verify_business)

    with TestClient(app) as client:
        await _set_kyb_capability(True)
        application_id = _prepare_application_with_business(client)

        response = client.post(
            f"/api/v2/admin/applications/{application_id}/business-verifications"
        )
        assert response.status_code == 502
        assert response.json()["code"] == "PROVIDER_REQUEST_FAILED"


async def test_business_verification_requires_a_business_profile(monkeypatch):
    monkeypatch.setattr(settings, "kyb_provider", "middesk")
    monkeypatch.setattr(settings, "middesk_api_key", "test-key")

    with TestClient(app) as client:
        await _set_kyb_capability(True)
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
                "business_name": "No Business Profile Co",
                "first_name": "No",
                "last_name": "Business",
                "email": f"owner-{unique}@example.com",
                "phone": "+15555550199",
                "postal_code": "33101",
                "consents": [
                    {"type": "APPLICATION_TERMS", "document_version": "v1", "accepted": True}
                ],
                "marketing": {"landing_page": "business-loans"},
            },
        )
        application_id = client.post(
            "/api/v2/applications", json={"lead_id": lead.json()["lead_id"]}
        ).json()["id"]

        response = client.post(
            f"/api/v2/admin/applications/{application_id}/business-verifications"
        )
        assert response.status_code == 409
