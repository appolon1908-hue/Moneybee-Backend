import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import compliance_models, identity_models
from app.db import SessionLocal
from app.main import app


def _prepare_matched_submission(client: TestClient) -> tuple[str, str, str]:
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
            "business_name": "Adverse Action Test Co",
            "first_name": "Ada",
            "last_name": "Verse",
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
            "legal_name": "Adverse Action Test Co LLC",
            "dba": "Adverse Action Test Co",
            "entity_type": "LLC",
            "state_formed": "FL",
            "industry": "TRANSPORTATION",
            "website": "https://example.com",
            "address": {"city": "Miami", "state": "FL"},
        },
    )
    client.put(
        f"/api/v2/applications/{application_id}/financial-profile",
        json={
            "annual_revenue": 600000,
            "monthly_revenue": 50000,
            "monthly_expenses": 30000,
            "existing_debt": 25000,
            "existing_positions": 1,
        },
    )
    client.post(
        f"/api/v2/applications/{application_id}/owners",
        json={
            "first_name": "Ada",
            "last_name": "Verse",
            "ownership_percent": 100,
            "title": "Owner",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550188",
            "address": {"city": "Miami", "state": "FL"},
        },
    )
    client.post(f"/api/v2/applications/{application_id}/submit")

    lender_id = str(uuid.uuid4())
    program_id = client.post(
        f"/api/v2/lenders/{lender_id}/programs",
        json={
            "lender_id": lender_id,
            "name": "Working Capital Standard",
            "product_type": "WORKING_CAPITAL",
            "min_amount": 10000,
            "max_amount": 250000,
            "minimum_monthly_revenue": 10000,
            "minimum_time_in_business_months": 12,
            "states": [],
            "excluded_industries": [],
        },
    ).json()["id"]
    client.post(f"/api/v2/applications/{application_id}/match")
    submission_id = next(
        item
        for item in client.post(
            f"/api/v2/admin/applications/{application_id}/prepare-matched-submissions"
        ).json()
        if item["program_id"] == program_id
    )["id"]
    return application_id, submission_id, lender_id


async def test_lender_decline_generates_an_adverse_action_notice():
    with TestClient(app) as client:
        application_id, submission_id, lender_id = _prepare_matched_submission(client)

        async with SessionLocal() as db:
            db.add(identity_models.Organization(
                id=uuid.UUID(lender_id), name="Test Capital Partners", organization_type="LENDER"
            ))
            await db.commit()

        decision = client.post(
            f"/api/v2/lender/submissions/{submission_id}/decisions",
            json={
                "expected_version": 1,
                "decision": "DECLINE",
                "reason_codes": ["LOW_DSCR", "HIGH_NSF"],
                "notes": "Debt service coverage below policy minimum.",
            },
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert decision.status_code == 201

        notices = client.get(
            f"/api/v2/admin/applications/{application_id}/adverse-action-notices"
        )
        assert notices.status_code == 200
        body = notices.json()
        assert len(body) == 1
        notice = body[0]
        assert notice["creditor_name"] == "Test Capital Partners"
        assert notice["principal_reasons"] == ["Low dscr", "High nsf"]
        assert "Test Capital Partners" in notice["notice_text"]
        assert "Equal Credit Opportunity Act" in notice["notice_text"]
        assert notice["status"] == "GENERATED"

        async with SessionLocal() as db:
            stored = await db.scalar(
                select(compliance_models.AdverseActionNotice).where(
                    compliance_models.AdverseActionNotice.application_id == uuid.UUID(application_id)
                )
            )
            assert stored is not None
            assert stored.lender_id == uuid.UUID(lender_id)


async def test_approve_decision_does_not_generate_a_notice():
    with TestClient(app) as client:
        application_id, submission_id, _lender_id = _prepare_matched_submission(client)

        decision = client.post(
            f"/api/v2/lender/submissions/{submission_id}/decisions",
            json={"expected_version": 1, "decision": "APPROVE", "reason_codes": []},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert decision.status_code == 201

        notices = client.get(
            f"/api/v2/admin/applications/{application_id}/adverse-action-notices"
        )
        assert notices.json() == []
