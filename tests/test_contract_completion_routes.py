import os
import uuid
from decimal import Decimal

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.main import app


async def _seed_application_and_offer() -> tuple[str, str, int]:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Contract",
            last_name="Reader",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550123",
            business_name="Contract Read Test LLC",
            funding_amount=25000,
            use_of_funds="WORKING_CAPITAL",
            time_in_business_months=24,
            monthly_revenue=30000,
            postal_code="33101",
        )
        db.add(lead)
        await db.flush()
        application = models.Application(
            lead_id=lead.id,
            requested_amount=Decimal("25000.00"),
            monthly_revenue=Decimal("30000.00"),
            time_in_business_months=24,
        )
        db.add(application)
        await db.flush()
        offer = models.Offer(
            application_id=application.id,
            lender_id=uuid.uuid4(),
            product_type="WORKING_CAPITAL",
            amount=Decimal("25000.00"),
            term_months=12,
            payment_frequency="MONTHLY",
            payment_amount=Decimal("2300.00"),
            total_repayment=Decimal("27600.00"),
            status="AVAILABLE",
        )
        db.add(offer)
        await db.commit()
        return (
            str(application.id),
            str(offer.id),
            application.completion_percentage,
        )


def test_me_permissions_returns_effective_local_authorization():
    with TestClient(app) as client:
        response = client.get("/api/v2/me/permissions")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "active_organization_id",
        "roles",
        "permissions",
        "membership_types",
    }
    assert payload["roles"] == sorted(payload["roles"])
    assert payload["permissions"] == sorted(payload["permissions"])
    assert payload["membership_types"] == sorted(payload["membership_types"])


def test_public_products_exposes_only_distinct_product_categories():
    with TestClient(app) as client:
        response = client.get("/api/v2/public/products")

    assert response.status_code == 200
    payload = response.json()
    assert all(set(item) == {"product_type"} for item in payload)
    product_types = [item["product_type"] for item in payload]
    assert product_types == sorted(set(product_types))
    assert all(product_types)


async def test_application_status_and_offer_detail_are_authorized_readbacks():
    application_id, offer_id, expected_completion = await _seed_application_and_offer()

    with TestClient(app) as client:
        status_response = client.get(f"/api/v2/applications/{application_id}/status")
        offer_response = client.get(f"/api/v2/offers/{offer_id}")
        missing_offer = client.get(f"/api/v2/offers/{uuid.uuid4()}")

    assert status_response.status_code == 200
    assert status_response.json() == {
        "application_id": application_id,
        "status": models.ApplicationStatus.APPLICATION_STARTED.value,
        "completion_percentage": expected_completion,
        "version": 1,
    }
    assert offer_response.status_code == 200
    assert offer_response.json()["id"] == offer_id
    assert offer_response.json()["application_id"] == application_id
    assert offer_response.json()["amount"] == "25000.00"
    assert missing_offer.status_code == 404
    assert missing_offer.headers["content-type"].startswith("application/problem+json")


def test_contract_completion_routes_are_v2_canonical_with_hidden_v1_aliases():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()
        compatibility_permissions = client.get("/api/v1/me/permissions")
        compatibility_products = client.get("/api/v1/public/products")

    expected_v2_paths = {
        "/api/v2/me/permissions": "identity_get_effective_permissions",
        "/api/v2/public/products": "public_list_products",
        "/api/v2/applications/{application_id}/status": "applications_get_status",
        "/api/v2/offers/{offer_id}": "offers_get_detail",
    }
    for path, operation_id in expected_v2_paths.items():
        assert path in openapi["paths"]
        assert openapi["paths"][path]["get"]["operationId"] == operation_id
        assert path.replace("/api/v2", "/api/v1", 1) not in openapi["paths"]
    assert compatibility_permissions.status_code == 200
    assert compatibility_products.status_code == 200
    assert compatibility_permissions.headers["Deprecation"] == "true"
    assert compatibility_products.headers["Deprecation"] == "true"
