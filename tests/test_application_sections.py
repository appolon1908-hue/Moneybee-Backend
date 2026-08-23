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

        credit_response = client.post(
            f"/api/v2/applications/{application_id}/credit-authorizations",
            json={
                "authorization_version": "2026-08",
                "document_hash": "a" * 64,
                "accepted": True,
            },
        )
        assert credit_response.status_code == 201
        assert credit_response.json()["accepted_by"] == "local-admin"

        complaint_response = client.post(
            f"/api/v2/applications/{application_id}/complaints",
            json={
                "category": "APPLICATION_SUPPORT",
                "description": "Please review the revenue information on this application.",
                "priority": "NORMAL",
            },
        )
        assert complaint_response.status_code == 201
        assert complaint_response.json()["status"] == "OPEN"

        preferences_response = client.put(
            "/api/v2/me/notification-preferences",
            json={
                "email_enabled": True,
                "sms_enabled": False,
                "in_app_enabled": True,
            },
        )
        assert preferences_response.status_code == 200
        assert preferences_response.json()["sms_enabled"] is False

        lender_id = str(uuid.uuid4())
        program_response = client.post(
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
        )
        assert program_response.status_code == 200
        program_id = program_response.json()["id"]

        match_response = client.post(
            f"/api/v2/applications/{application_id}/match"
        )
        assert match_response.status_code == 200
        assert match_response.json()[0]["eligible"] is True

        submission_response = client.post(
            f"/api/v2/admin/applications/{application_id}"
            "/prepare-matched-submissions"
        )
        assert submission_response.status_code == 200
        submission = submission_response.json()[0]
        assert submission["status"] == "DRAFT"

        condition_response = client.post(
            f"/api/v2/lender/submissions/{submission['id']}/conditions",
            json={"description": "Provide the most recent operating statement."},
        )
        assert condition_response.status_code == 201

        conditions_response = client.get(
            f"/api/v2/applications/{application_id}/conditions"
        )
        assert conditions_response.status_code == 200
        assert len(conditions_response.json()) == 1

        offer_response = client.post(
            f"/api/v2/lender/submissions/{submission['id']}/offers",
            json={
                "application_id": application_id,
                "lender_id": lender_id,
                "program_id": program_id,
                "product_type": "WORKING_CAPITAL",
                "amount": 50000,
                "term_months": 12,
                "payment_frequency": "MONTHLY",
                "payment_amount": 5000,
                "apr": 15,
                "origination_fee": 500,
                "total_repayment": 60000,
            },
        )
        assert offer_response.status_code == 201
        offer_id = offer_response.json()["id"]

        accept_key = uuid.uuid4().hex
        accepted_response = client.post(
            f"/api/v2/offers/{offer_id}/accept",
            headers={"Idempotency-Key": accept_key},
        )
        assert accepted_response.status_code == 200
        assert accepted_response.json()["status"] == "ACCEPTED"

        replay_response = client.post(
            f"/api/v2/offers/{offer_id}/accept",
            headers={"Idempotency-Key": accept_key},
        )
        assert replay_response.status_code == 200
        assert replay_response.json()["id"] == offer_id

        funding_response = client.get(
            f"/api/v2/applications/{application_id}/funding"
        )
        assert funding_response.status_code == 200
        assert funding_response.json()["status"] == "CONDITIONS_PENDING"
