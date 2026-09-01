"""Covers 5 endpoints the backend spec's "API contract target" lists that
were missing entirely from the running app (confirmed by diffing
app.openapi()'s actual paths against docs/MONEYBEE_V3_BACKEND_SPEC.md's
explicit target list):

- GET /public/products - a public product catalog for the marketing site
  and prequalification form, aggregated from real active LenderProgram rows
  rather than a hardcoded list.
- PATCH /public/prequalifications/{lead_id} - resuming/editing a
  prequalification before it converts into a full application.
- GET /me/permissions - a lightweight permission-only view of the current
  principal (GET /me already includes permissions inline; this is the
  dedicated endpoint the spec names).
- GET /applications/{id}/consents - reading back what was consented to at
  intake (the Consent model already existed; nothing read it back).
- POST /offers/{offer_id}/decline - the spec's "offer list/comparison/
  accept/decline" target; only accept existed.
"""

import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def _submit_prequalification(client: TestClient, **overrides) -> dict:
    unique = uuid.uuid4().hex
    payload = {
        "funding_amount": 75000,
        "currency": "USD",
        "use_of_funds": "WORKING_CAPITAL",
        "time_in_business_months": 24,
        "monthly_revenue": 50000,
        "business_name": "Missing Endpoint Test Co",
        "first_name": "Riley",
        "last_name": "Gap",
        "email": f"owner-{unique}@example.com",
        "phone": "+15555550177",
        "postal_code": "33101",
        "consents": [{"type": "APPLICATION_TERMS", "document_version": "v1", "accepted": True}],
        "marketing": {"landing_page": "business-loans"},
    }
    payload.update(overrides)
    response = client.post(
        "/api/v2/public/prequalifications",
        headers={"Idempotency-Key": unique},
        json=payload,
    )
    assert response.status_code == 202
    return response.json()


def _prepare_matched_submission(client: TestClient) -> tuple[str, str, str, str]:
    unique = uuid.uuid4().hex
    lead = _submit_prequalification(client)
    application_id = client.post(
        "/api/v2/applications", json={"lead_id": lead["lead_id"]}
    ).json()["id"]
    client.put(
        f"/api/v2/applications/{application_id}/business",
        json={
            "legal_name": "Missing Endpoint Test Co LLC",
            "dba": "Missing Endpoint Test Co",
            "entity_type": "LLC",
            "state_formed": "CA",
            "industry": "TRANSPORTATION",
            "website": "https://example.com",
            "address": {"city": "Los Angeles", "state": "CA"},
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
            "first_name": "Riley",
            "last_name": "Gap",
            "ownership_percent": 100,
            "title": "Owner",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550177",
            "address": {"city": "Los Angeles", "state": "CA"},
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
    return application_id, submission_id, lender_id, program_id


def test_public_products_reflects_real_active_lender_programs():
    with TestClient(app) as client:
        lender_id = str(uuid.uuid4())
        client.post(
            f"/api/v2/lenders/{lender_id}/programs",
            json={
                "lender_id": lender_id,
                "name": "Equipment Program",
                "product_type": "EQUIPMENT_FINANCING",
                "min_amount": 15000,
                "max_amount": 300000,
                "minimum_monthly_revenue": 10000,
                "minimum_time_in_business_months": 12,
                "states": [],
                "excluded_industries": [],
            },
        )

        products = client.get("/api/v2/public/products")
        assert products.status_code == 200
        body = products.json()
        assert isinstance(body, list)
        equipment = next(
            item for item in body if item["product_type"] == "EQUIPMENT_FINANCING"
        )
        assert equipment["display_name"] == "Equipment Financing"
        assert equipment["min_amount"] == "15000.00"
        assert equipment["max_amount"] == "300000.00"
        assert equipment["lender_count"] >= 1


def test_unknown_product_type_gets_a_humanized_fallback_name():
    with TestClient(app) as client:
        lender_id = str(uuid.uuid4())
        client.post(
            f"/api/v2/lenders/{lender_id}/programs",
            json={
                "lender_id": lender_id,
                "name": "Novel Program",
                "product_type": "REVENUE_BASED_FINANCING",
                "min_amount": 5000,
                "max_amount": 100000,
                "minimum_monthly_revenue": 5000,
                "minimum_time_in_business_months": 6,
                "states": [],
                "excluded_industries": [],
            },
        )
        products = client.get("/api/v2/public/products").json()
        novel = next(
            item for item in products if item["product_type"] == "REVENUE_BASED_FINANCING"
        )
        assert novel["display_name"] == "Revenue Based Financing"


def test_prequalification_can_be_edited_before_it_becomes_an_application():
    with TestClient(app) as client:
        lead = _submit_prequalification(client)
        lead_id = lead["lead_id"]

        updated = client.patch(
            f"/api/v2/public/prequalifications/{lead_id}",
            json={"funding_amount": 90000, "business_name": "Renamed Test Co"},
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["funding_amount"] == "90000.00"
        assert body["business_name"] == "Renamed Test Co"
        # Untouched fields survive a partial update.
        assert body["use_of_funds"] == "WORKING_CAPITAL"


def test_editing_an_unknown_lead_returns_404():
    with TestClient(app) as client:
        response = client.patch(
            f"/api/v2/public/prequalifications/{uuid.uuid4()}",
            json={"funding_amount": 50000},
        )
        assert response.status_code == 404


def test_prequalification_cannot_be_edited_once_converted_to_an_application():
    with TestClient(app) as client:
        lead = _submit_prequalification(client)
        client.post("/api/v2/applications", json={"lead_id": lead["lead_id"]})

        blocked = client.patch(
            f"/api/v2/public/prequalifications/{lead['lead_id']}",
            json={"funding_amount": 50000},
        )
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "PREQUALIFICATION_ALREADY_CONVERTED"


def test_me_permissions_matches_the_wildcard_local_bypass_principal():
    with TestClient(app) as client:
        response = client.get("/api/v2/me/permissions")
        assert response.status_code == 200
        assert response.json() == {"permissions": ["*"]}


def test_application_consents_lists_what_was_accepted_at_intake():
    with TestClient(app) as client:
        lead = _submit_prequalification(
            client,
            consents=[
                {"type": "APPLICATION_TERMS", "document_version": "v1", "accepted": True},
                {"type": "CREDIT_PULL_AUTHORIZATION", "document_version": "v2", "accepted": True},
            ],
        )
        application_id = client.post(
            "/api/v2/applications", json={"lead_id": lead["lead_id"]}
        ).json()["id"]

        consents = client.get(f"/api/v2/applications/{application_id}/consents")
        assert consents.status_code == 200
        body = consents.json()
        assert {item["consent_type"] for item in body} == {
            "APPLICATION_TERMS",
            "CREDIT_PULL_AUTHORIZATION",
        }
        assert all(item["evidence"]["accepted"] is True for item in body)


def test_declining_an_offer_marks_it_declined_and_leaves_application_untouched():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = _prepare_matched_submission(
            client
        )
        offer = client.post(
            f"/api/v2/lender/submissions/{submission_id}/offers",
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
            },
        )
        assert offer.status_code == 201
        offer_id = offer.json()["id"]

        declined = client.post(
            f"/api/v2/offers/{offer_id}/decline",
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert declined.status_code == 200
        assert declined.json()["status"] == "DECLINED"

        application = client.get(f"/api/v2/applications/{application_id}").json()
        assert application["status"] != "OFFER_ACCEPTED"


def test_declining_an_offer_is_idempotent():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = _prepare_matched_submission(
            client
        )
        offer = client.post(
            f"/api/v2/lender/submissions/{submission_id}/offers",
            json={
                "application_id": application_id,
                "lender_id": lender_id,
                "program_id": program_id,
                "product_type": "WORKING_CAPITAL",
                "amount": 40000,
                "term_months": 12,
                "payment_frequency": "MONTHLY",
                "payment_amount": 4000,
                "apr": 12,
            },
        ).json()
        offer_id = offer["id"]
        key = uuid.uuid4().hex

        first = client.post(
            f"/api/v2/offers/{offer_id}/decline", headers={"Idempotency-Key": key}
        )
        replay = client.post(
            f"/api/v2/offers/{offer_id}/decline", headers={"Idempotency-Key": key}
        )
        assert first.status_code == replay.status_code == 200
        assert first.json() == replay.json()


def test_declining_an_offer_that_is_not_available_conflicts():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = _prepare_matched_submission(
            client
        )
        offer = client.post(
            f"/api/v2/lender/submissions/{submission_id}/offers",
            json={
                "application_id": application_id,
                "lender_id": lender_id,
                "program_id": program_id,
                "product_type": "WORKING_CAPITAL",
                "amount": 30000,
                "term_months": 12,
                "payment_frequency": "MONTHLY",
                "payment_amount": 3000,
                "apr": 10,
            },
        ).json()
        offer_id = offer["id"]

        accepted = client.post(
            f"/api/v2/offers/{offer_id}/accept",
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert accepted.status_code == 200
        conflict = client.post(
            f"/api/v2/offers/{offer_id}/decline",
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert conflict.status_code == 409
