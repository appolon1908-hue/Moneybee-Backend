import copy
import hashlib
import hmac
import json
import time
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


BASE = {
    "marketing": {"landing_page": "contact", "utm_source": "test"},
    "consents": [
        {
            "type": "ELECTRONIC_COMMUNICATIONS",
            "document_version": "2026-08-26",
            "document_hash": "0" * 64,
            "accepted": True,
        }
    ],
}


def _post(client: TestClient, path: str, payload: dict, key: str):
    return client.post(
        f"/api/v2{path}",
        json=payload,
        headers={"Idempotency-Key": key, "X-Request-ID": f"req-{key}"},
    )


def test_public_intake_forms_are_idempotent_and_create_crm_events():
    cases = [
        (
            "/public/contact-requests",
            {
                **BASE,
                "first_name": "Ana",
                "last_name": "Diaz",
                "email": "ANA@example.com",
                "phone": "(555) 555-0100",
                "business_name": "Honey Retail",
                "topic": "Application help",
                "message": "Please contact me about a business funding application.",
                "preferred_channel": "EITHER",
            },
            "CONTACT_REQUEST",
        ),
        (
            "/public/callback-requests",
            {
                **BASE,
                "first_name": "Luis",
                "last_name": "Mora",
                "email": "luis@example.com",
                "phone": "+15555550101",
                "business_name": "Mora Trucking",
                "preferred_time": "Weekdays after 2 PM",
                "timezone": "America/New_York",
                "reason": "Working capital",
            },
            "CALLBACK_REQUEST",
        ),
        (
            "/public/lender-partner-inquiries",
            {
                **BASE,
                "first_name": "Jamie",
                "last_name": "Banker",
                "email": "jamie@bankexample.com",
                "institution_name": "Example Community Bank",
                "role": "Partnerships Director",
                "product_types": ["TERM_LOAN"],
                "states": ["fl", "NY"],
                "annual_originations": 10000000,
            },
            "LENDER_PARTNER_INQUIRY",
        ),
        (
            "/public/referral-partner-inquiries",
            {
                **BASE,
                "first_name": "Rosa",
                "last_name": "Broker",
                "email": "rosa@brokerexample.com",
                "company_name": "Rosa Business Advisors",
                "partner_type": "BROKER",
                "states": ["FL"],
                "estimated_monthly_leads": 20,
            },
            "REFERRAL_PARTNER_INQUIRY",
        ),
        (
            "/public/deal-submission-inquiries",
            {
                **BASE,
                "first_name": "Devon",
                "last_name": "Owner",
                "email": "devon@example.com",
                "phone": "+15555550104",
                "business_name": "Devon Construction",
                "requested_amount": 125000,
                "monthly_revenue": 85000,
                "time_in_business_months": 48,
                "industry": "Construction",
                "state": "fl",
                "use_of_funds": "Equipment",
            },
            "DEAL_SUBMISSION_INQUIRY",
        ),
    ]

    with TestClient(app) as client:
        for path, payload, intake_type in cases:
            key = uuid.uuid4().hex
            first = _post(client, path, payload, key)
            assert first.status_code == 202, first.text
            assert first.json()["intake_type"] == intake_type
            replay = _post(client, path, payload, key)
            assert replay.status_code == 202
            assert replay.json() == first.json()

            collision_payload = copy.deepcopy(payload)
            collision_payload["first_name"] = "Changed"
            collision = _post(client, path, collision_payload, key)
            assert collision.status_code == 409
            assert collision.json()["detail"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"

        deliveries = client.get(
            "/api/v2/admin/crm-deliveries",
            headers={"Authorization": "Bearer local-test"},
        )
        assert deliveries.status_code == 200, deliveries.text
        event_types = {item["intake_type"] for item in deliveries.json() if item["intake_type"]}
        assert {case[2] for case in cases}.issubset(event_types)


def test_codestra_receipt_rejects_replay_collision(monkeypatch):
    secret = "codestra-receipt-test"
    monkeypatch.setattr(settings, "middleware_provider", "codestra")
    monkeypatch.setattr(settings, "codestra_middleware_webhook_secret", secret)
    payload = {"message_id": "receipt-1", "event_type": "crm.delivery.accepted"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Codestra-Timestamp": timestamp,
        "X-Codestra-Signature": signature,
    }
    with TestClient(app) as client:
        first = client.post("/api/v2/webhooks/codestra/receipts", content=body, headers=headers)
        assert first.status_code == 202, first.text
        replay = client.post("/api/v2/webhooks/codestra/receipts", content=body, headers=headers)
        assert replay.status_code == 202
        assert replay.json()["duplicate"] is True

        changed = json.dumps({**payload, "status": "changed"}, separators=(",", ":")).encode()
        changed_signature = hmac.new(
            secret.encode(),
            timestamp.encode() + b"." + changed,
            hashlib.sha256,
        ).hexdigest()
        collision = client.post(
            "/api/v2/webhooks/codestra/receipts",
            content=changed,
            headers={**headers, "X-Codestra-Signature": changed_signature},
        )
        assert collision.status_code == 409
