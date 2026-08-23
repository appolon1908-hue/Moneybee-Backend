import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def test_authoritative_requirement_fraud_and_underwriting_records():
    unique = uuid.uuid4().hex
    prequalification = {
        "funding_amount": 90000,
        "currency": "USD",
        "use_of_funds": "WORKING_CAPITAL",
        "time_in_business_months": 36,
        "monthly_revenue": 75000,
        "business_name": f"Snapshot Logistics {unique}",
        "first_name": "Domain",
        "last_name": "Tester",
        "email": f"domain-{unique}@example.com",
        "phone": f"+1555{unique[:7]}",
        "postal_code": "33101",
        "consents": [
            {
                "type": "APPLICATION_TERMS",
                "document_version": "v1",
                "accepted": True,
            }
        ],
        "marketing": {"landing_page": "business-loans"},
    }

    with TestClient(app) as client:
        lead = client.post(
            "/api/v2/public/prequalifications",
            json=prequalification,
            headers={"Idempotency-Key": unique},
        )
        assert lead.status_code == 202
        application = client.post(
            "/api/v2/applications",
            json={"lead_id": lead.json()["lead_id"]},
        )
        assert application.status_code == 200
        application_id = application.json()["id"]

        updated = client.patch(
            f"/api/v2/applications/{application_id}",
            json={
                "industry": "TRANSPORTATION",
                "state": "FL",
                "version": application.json()["version"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "APPLICATION_IN_PROGRESS"

        snapshot = client.post(
            f"/api/v2/applications/{application_id}/requirement-snapshots"
        )
        assert snapshot.status_code == 201
        assert snapshot.json()["policy_version"] == 2
        assert snapshot.json()["ready_for_submission"] is False
        assert {
            item["route"] for item in snapshot.json()["requirements"]
        } >= {"/business", "/financials", "/owners"}

        assessment = client.post(
            f"/api/v2/admin/applications/{application_id}/fraud-assessments"
        )
        assert assessment.status_code == 201
        assert assessment.json()["decision"] == "PASS"
        assert assessment.json()["flags"] == []

        escalated = client.post(
            f"/api/v2/admin/applications/{application_id}/underwriting/reviews",
            json={
                "decision": "FRAUD_REVIEW",
                "reason_codes": ["MANUAL_REVIEW"],
                "notes": "Escalated by deterministic test.",
            },
        )
        assert escalated.status_code == 201
        assert escalated.json()["decision"] == "FRAUD_REVIEW"

        approved = client.post(
            f"/api/v2/admin/applications/{application_id}/underwriting/reviews",
            json={
                "decision": "APPROVE",
                "reason_codes": ["MANUAL_CLEAR"],
            },
        )
        assert approved.status_code == 201

        current = client.get(f"/api/v2/applications/{application_id}")
        assert current.status_code == 200
        assert current.json()["status"] == "READY_FOR_MATCHING"

        catalog = client.get("/api/v2/admin/catalog/applications")
        assert catalog.status_code == 200
        assert any(row["id"] == application_id for row in catalog.json())
