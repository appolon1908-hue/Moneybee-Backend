import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def test_lender_dashboard_programs_and_versioned_decision():
    unique = uuid.uuid4().hex
    lender_id = str(uuid.uuid4())
    with TestClient(app) as client:
        lead = client.post(
            "/api/v2/public/prequalifications",
            headers={"Idempotency-Key": unique},
            json={
                "funding_amount": 40000,
                "currency": "USD",
                "use_of_funds": "WORKING_CAPITAL",
                "time_in_business_months": 36,
                "monthly_revenue": 30000,
                "business_name": "Lender Portal Test",
                "first_name": "Test",
                "last_name": "Owner",
                "email": f"{unique}@example.com",
                "phone": "+15555550188",
                "postal_code": "33101",
                "consents": [{"type": "APPLICATION_TERMS", "document_version": "v1", "accepted": True}],
                "marketing": {"landing_page": "portal-tests"},
            },
        )
        application = client.post(
            "/api/v2/applications", json={"lead_id": lead.json()["lead_id"]}
        ).json()
        application_id = application["id"]
        assert client.put(
            f"/api/v2/applications/{application_id}/business",
            json={
                "legal_name": "Lender Portal Test LLC",
                "entity_type": "LLC",
                "state_formed": "FL",
                "industry": "SERVICES",
                "address": {"state": "FL"},
            },
        ).status_code == 200
        assert client.put(
            f"/api/v2/applications/{application_id}/financial-profile",
            json={
                "annual_revenue": 360000,
                "monthly_revenue": 30000,
                "monthly_expenses": 15000,
                "existing_debt": 0,
                "existing_positions": 0,
            },
        ).status_code == 200
        assert client.post(
            f"/api/v2/applications/{application_id}/owners",
            json={
                "first_name": "Test",
                "last_name": "Owner",
                "ownership_percent": 100,
                "address": {"state": "FL"},
            },
        ).status_code == 201
        assert client.post(
            f"/api/v2/applications/{application_id}/submit"
        ).status_code == 200
        program = client.post(
            f"/api/v2/lenders/{lender_id}/programs",
            json={
                "lender_id": lender_id,
                "name": "Portal Working Capital",
                "product_type": "WORKING_CAPITAL",
                "min_amount": 10000,
                "max_amount": 100000,
                "minimum_monthly_revenue": 10000,
                "minimum_time_in_business_months": 12,
                "states": [],
                "excluded_industries": [],
            },
        )
        assert program.status_code == 200
        client.post(f"/api/v2/applications/{application_id}/match")
        submissions = client.post(
            f"/api/v2/admin/applications/{application_id}/prepare-matched-submissions"
        )
        assert submissions.status_code == 200
        submission_id = submissions.json()[0]["id"]

        dashboard = client.get("/api/v2/lender/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["programs"] >= 1

        workspace = client.get(
            f"/api/v2/lender/submissions/{submission_id}/workspace"
        )
        assert workspace.status_code == 200
        assert workspace.json()["submission"]["version"] == 1

        decision = client.post(
            f"/api/v2/lender/submissions/{submission_id}/decisions",
            headers={"Idempotency-Key": uuid.uuid4().hex},
            json={
                "expected_version": 1,
                "decision": "APPROVE",
                "reason_codes": ["CASH_FLOW_ACCEPTABLE"],
                "notes": "Approved for offer preparation.",
            },
        )
        assert decision.status_code == 201
        assert decision.json()["status"] == "APPROVED"
        assert decision.json()["version"] == 2
