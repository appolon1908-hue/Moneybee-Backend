import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def test_admin_overview_tasks_notifications_and_conversation_reply():
    unique = uuid.uuid4().hex
    with TestClient(app) as client:
        lead = client.post(
            "/api/v2/public/prequalifications",
            headers={"Idempotency-Key": unique},
            json={
                "funding_amount": 25000,
                "currency": "USD",
                "use_of_funds": "WORKING_CAPITAL",
                "time_in_business_months": 18,
                "monthly_revenue": 18000,
                "business_name": "Admin Portal Test",
                "first_name": "Admin",
                "last_name": "Test",
                "email": f"{unique}@example.com",
                "phone": "+15555550177",
                "postal_code": "33101",
                "consents": [{"type": "APPLICATION_TERMS", "document_version": "v1", "accepted": True}],
                "marketing": {"landing_page": "portal-tests"},
            },
        )
        application = client.post(
            "/api/v2/applications", json={"lead_id": lead.json()["lead_id"]}
        ).json()

        task = client.post(
            "/api/v2/admin/tasks",
            json={
                "application_id": application["id"],
                "assignee_subject": "local-admin",
                "task_type": "APPLICATION_REVIEW",
                "title": "Review application",
                "priority": "HIGH",
            },
        )
        assert task.status_code == 201
        task_id = task.json()["id"]
        update = client.patch(
            f"/api/v2/admin/tasks/{task_id}", json={"status": "COMPLETED"}
        )
        assert update.status_code == 200
        assert update.json()["status"] == "COMPLETED"

        notification = client.post(
            "/api/v2/admin/notifications",
            json={
                "application_id": application["id"],
                "subject": "local-admin",
                "category": "APPLICATION",
                "title": "Application updated",
                "body": "Your application review has started.",
                "action_path": "/application",
            },
        )
        assert notification.status_code == 201

        conversation = client.post(
            "/api/v2/borrower/conversations",
            json={
                "application_id": application["id"],
                "topic": "Help request",
                "body": "Please help with the application.",
            },
        )
        assert conversation.status_code == 201
        reply = client.post(
            f"/api/v2/admin/conversations/{conversation.json()['id']}/messages",
            json={"body": "A MoneyBee specialist is reviewing the request."},
        )
        assert reply.status_code == 201

        overview = client.get("/api/v2/admin/overview")
        assert overview.status_code == 200
        assert overview.json()["applications"] >= 1
        assert overview.json()["unread_notifications"] >= 1

        audit = client.get("/api/v2/admin/audit-events?limit=20")
        assert audit.status_code == 200
        assert audit.json()["meta"]["total"] >= 3
