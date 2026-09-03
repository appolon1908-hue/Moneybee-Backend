import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def create_application(client: TestClient) -> str:
    unique = uuid.uuid4().hex
    lead = client.post(
        "/api/v2/public/prequalifications",
        headers={"Idempotency-Key": unique},
        json={
            "funding_amount": 50000,
            "currency": "USD",
            "use_of_funds": "WORKING_CAPITAL",
            "time_in_business_months": 24,
            "monthly_revenue": 25000,
            "business_name": "Portal Test LLC",
            "first_name": "Test",
            "last_name": "Owner",
            "email": f"{unique}@example.com",
            "phone": "+15555550199",
            "postal_code": "33101",
            "consents": [
                {
                    "type": "APPLICATION_TERMS",
                    "document_version": "v1",
                    "accepted": True,
                }
            ],
            "marketing": {"landing_page": "portal-tests"},
        },
    )
    assert lead.status_code == 202
    application = client.post(
        "/api/v2/applications",
        json={"lead_id": lead.json()["lead_id"]},
    )
    assert application.status_code == 200
    return application.json()["id"]


def test_borrower_overview_messages_and_safe_document_gate():
    with TestClient(app) as client:
        application_id = create_application(client)
        overview = client.get("/api/v2/borrower/overview")
        assert overview.status_code == 200
        assert overview.json()["active_application"]["id"] == application_id

        conversation = client.post(
            "/api/v2/borrower/conversations",
            json={
                "application_id": application_id,
                "topic": "Application question",
                "body": "Please confirm the next required step.",
            },
        )
        assert conversation.status_code == 201
        conversation_id = conversation.json()["id"]

        reply = client.post(
            f"/api/v2/borrower/conversations/{conversation_id}/messages",
            json={"body": "I have uploaded the requested information."},
        )
        assert reply.status_code == 201
        messages = client.get(
            f"/api/v2/borrower/conversations/{conversation_id}/messages"
        )
        assert messages.status_code == 200
        assert len(messages.json()) == 2

        upload = client.post(
            f"/api/v2/borrower/applications/{application_id}/documents/upload-sessions",
            json={
                "document_type": "BANK_STATEMENT",
                "original_file_name": "statement.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1024,
                "sha256": "a" * 64,
            },
        )
        assert upload.status_code == 503
        assert upload.json()["code"] == "CAPABILITY_UNAVAILABLE"
