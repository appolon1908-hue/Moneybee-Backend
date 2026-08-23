import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def test_borrower_application_sections_and_submission_flow():
    unique = uuid.uuid4().hex
    prequalification = {
        "funding_amount": 75000,
        "currency": "USD",
        "use_of_funds": "WORKING_CAPITAL",
        "time_in_business_months": 24,
        "monthly_revenue": 50000,
        "business_name": "Honey Transport",
        "first_name": "Ralph",
        "last_name": "Appolon",
        "email": f"owner-{unique}@example.com",
        "phone": "+15555550123",
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
        lead_response = client.post(
            "/api/v2/public/prequalifications",
            json=prequalification,
            headers={"Idempotency-Key": unique},
        )
        assert lead_response.status_code == 202
        lead_id = lead_response.json()["lead_id"]

        application_response = client.post(
            "/api/v2/applications",
            json={"lead_id": lead_id},
        )
        assert application_response.status_code == 200
        application_id = application_response.json()["id"]

        business_response = client.put(
            f"/api/v2/applications/{application_id}/business",
            json={
                "legal_name": "Honey Transport LLC",
                "dba": "Honey Transport",
                "entity_type": "LLC",
                "state_formed": "FL",
                "industry": "TRANSPORTATION",
                "website": "https://example.com",
                "address": {"city": "Miami", "state": "FL"},
            },
        )
        assert business_response.status_code == 200

        financial_response = client.put(
            f"/api/v2/applications/{application_id}/financial-profile",
            json={
                "annual_revenue": 600000,
                "monthly_revenue": 50000,
                "monthly_expenses": 30000,
                "existing_debt": 25000,
                "existing_positions": 1,
            },
        )
        assert financial_response.status_code == 200

        owner_response = client.post(
            f"/api/v2/applications/{application_id}/owners",
            json={
                "first_name": "Ralph",
                "last_name": "Appolon",
                "ownership_percent": 100,
                "title": "Owner",
                "email": f"owner-{unique}@example.com",
                "phone": "+15555550123",
                "address": {"city": "Miami", "state": "FL"},
            },
        )
        assert owner_response.status_code == 201

        requirements_response = client.get(
            f"/api/v2/applications/{application_id}/requirements"
        )
        assert requirements_response.status_code == 200
        requirements = requirements_response.json()
        assert requirements["completion_percentage"] == 100
        assert requirements["ready_to_submit"] is True
        assert all(item["complete"] for item in requirements["requirements"])

        submit_response = client.post(
            f"/api/v2/applications/{application_id}/submit"
        )
        assert submit_response.status_code == 200
        assert submit_response.json()["status"] == "READY_FOR_MATCHING"

        timeline_response = client.get(
            f"/api/v2/applications/{application_id}/timeline"
        )
        assert timeline_response.status_code == 200
        assert timeline_response.json()[-1]["to_status"] == "READY_FOR_MATCHING"
