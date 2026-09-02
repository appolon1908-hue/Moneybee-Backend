import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models, worker
from app.db import SessionLocal
from app.integration_models import IntegrationInboxMessage
from app.main import app


def _prepare_matched_submission(client: TestClient) -> tuple[str, str, str, str]:
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
            "business_name": "Contract Engine Test Co",
            "first_name": "Cara",
            "last_name": "Signer",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550177",
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
            "legal_name": "Contract Engine Test Co LLC",
            "dba": "Contract Engine Test Co",
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
            "first_name": "Cara",
            "last_name": "Signer",
            "ownership_percent": 100,
            "title": "Owner",
            "email": f"owner-{unique}@example.com",
            "phone": "+15555550177",
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
    return application_id, submission_id, lender_id, program_id


def _create_and_accept_offer(
    client: TestClient,
    application_id: str,
    submission_id: str,
    lender_id: str,
    program_id: str,
) -> None:
    offer_id = client.post(
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
            "origination_fee": 500,
            "total_repayment": 60000,
        },
    ).json()["id"]
    acknowledged = client.post(
        f"/api/v2/offers/{offer_id}/commercial-financing-disclosure/acknowledge"
    )
    assert acknowledged.status_code == 200
    accepted = client.post(
        f"/api/v2/offers/{offer_id}/accept",
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert accepted.status_code == 200


async def test_contract_is_created_in_draft_when_conditions_satisfied():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = (
            _prepare_matched_submission(client)
        )
        # No conditions attached -> vacuously satisfied at acceptance.
        _create_and_accept_offer(
            client, application_id, submission_id, lender_id, program_id
        )

        contract = client.get(f"/api/v2/applications/{application_id}/contract")
        assert contract.status_code == 200
        assert contract.json()["status"] == "DRAFT"
        assert contract.json()["application_id"] == application_id


async def test_contract_void_is_idempotent():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = (
            _prepare_matched_submission(client)
        )
        _create_and_accept_offer(
            client, application_id, submission_id, lender_id, program_id
        )
        contract_id = client.get(
            f"/api/v2/applications/{application_id}/contract"
        ).json()["id"]

        key = uuid.uuid4().hex
        first = client.post(
            f"/api/v2/admin/contracts/{contract_id}/void",
            json={"reason": "Offer superseded before signing."},
            headers={"Idempotency-Key": key},
        )
        assert first.status_code == 200
        assert first.json()["status"] == "VOIDED"

        replay = client.post(
            f"/api/v2/admin/contracts/{contract_id}/void",
            json={"reason": "Offer superseded before signing."},
            headers={"Idempotency-Key": key},
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "VOIDED"

        # A different idempotency key targeting the *same* already-VOIDED
        # state is still a no-op success (transition_contract treats
        # "already at the target status" as accomplished, not an error -
        # same rule transition_funding/transition_application use).
        also_voided = client.post(
            f"/api/v2/admin/contracts/{contract_id}/void",
            json={"reason": "Offer superseded before signing."},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert also_voided.status_code == 200
        assert also_voided.json()["status"] == "VOIDED"

        # A genuinely invalid transition (SIGNED has no outbound edges,
        # unlike DRAFT/SENT) still correctly 409s.
        async with SessionLocal() as db:
            contract = await db.get(models.Contract, uuid.UUID(contract_id))
            contract.status = "SIGNED"
            await db.commit()
        invalid = client.post(
            f"/api/v2/admin/contracts/{contract_id}/void",
            json={"reason": "Too late, already signed."},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert invalid.status_code == 409
        assert invalid.json()["code"] == "INVALID_CONTRACT_TRANSITION"


async def test_sent_contract_is_voided_at_provider_before_local_transition(monkeypatch):
    calls = []

    class FakeESign:
        async def void_envelope(self, **kwargs):
            calls.append(kwargs)
            return {"status": "voided"}

    monkeypatch.setattr("app.admin_routes.esign_adapter", lambda: FakeESign())
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = _prepare_matched_submission(client)
        _create_and_accept_offer(client, application_id, submission_id, lender_id, program_id)
        contract_id = client.get(f"/api/v2/applications/{application_id}/contract").json()["id"]
        async with SessionLocal() as db:
            contract = await db.get(models.Contract, uuid.UUID(contract_id))
            contract.status = "SENT"
            contract.external_envelope_id = "provider-envelope-void"
            await db.commit()
        response = client.post(
            f"/api/v2/admin/contracts/{contract_id}/void",
            json={"reason": "Offer superseded."},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "VOIDED"
        assert calls == [{"envelope_id": "provider-envelope-void", "reason": "Offer superseded."}]


async def test_send_pending_contract_envelope_leaves_draft_when_provider_disabled():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = (
            _prepare_matched_submission(client)
        )
        _create_and_accept_offer(
            client, application_id, submission_id, lender_id, program_id
        )
        contract_id = client.get(
            f"/api/v2/applications/{application_id}/contract"
        ).json()["id"]

    os.environ["ESIGN_LIVE_SEND"] = "true"
    try:
        # send_pending_contract_envelope() claims the globally-oldest DRAFT
        # contract, not necessarily this test's own - other tests in this
        # file/suite may leave their own DRAFT contracts behind. Since a
        # disabled esign_provider makes *every* send fail the same way, the
        # outcome that actually matters (never silently marked SENT) holds
        # regardless of which one gets claimed, so this doesn't assert on
        # which contract came back.
        await worker.send_pending_contract_envelope()
    finally:
        os.environ["ESIGN_LIVE_SEND"] = "false"

    async with SessionLocal() as db:
        contract = await db.get(models.Contract, uuid.UUID(contract_id))
        # esign_provider defaults to "disabled" in tests -> ProviderError ->
        # left as DRAFT for the next attempt, never silently marked sent.
        assert contract.status == "DRAFT"
        attempted = await db.scalar(
            select(models.Contract)
            .where(models.Contract.provider_attempt_count > 0)
            .order_by(models.Contract.provider_attempt_count.desc())
        )
        assert attempted is not None
        assert attempted.provider_last_error is not None
        assert attempted.provider_next_attempt_at is not None


async def test_process_pending_docusign_event_signs_contract_and_advances_funding():
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = (
            _prepare_matched_submission(client)
        )
        _create_and_accept_offer(
            client, application_id, submission_id, lender_id, program_id
        )
        contract_id = client.get(
            f"/api/v2/applications/{application_id}/contract"
        ).json()["id"]

    envelope_id = f"envelope-{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        contract = await db.get(models.Contract, uuid.UUID(contract_id))
        contract.status = "SENT"
        contract.external_envelope_id = envelope_id
        db.add(
            IntegrationInboxMessage(
                provider="docusign",
                event_id=uuid.uuid4().hex,
                event_type="envelope-completed",
                payload={
                    "event": "envelope-completed",
                    "data": {
                        "envelopeId": envelope_id,
                        "envelopeSummary": {"status": "completed"},
                    },
                },
                payload_hash=uuid.uuid4().hex,
                signature_valid=True,
                status="RECEIVED",
            )
        )
        await db.commit()

    processed_id = await worker.process_pending_docusign_event()
    assert processed_id is not None

    async with SessionLocal() as db:
        contract = await db.get(models.Contract, uuid.UUID(contract_id))
        assert contract.status == "SIGNED"
        assert contract.signed_at is not None

        funding = await db.scalar(
            select(models.Funding).where(
                models.Funding.application_id == uuid.UUID(application_id)
            )
        )
        assert funding.status == "CONTRACT_SIGNED"


async def test_unmatched_docusign_callback_remains_retryable():
    message_id = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(IntegrationInboxMessage(
            id=message_id,
            provider="docusign",
            event_id=uuid.uuid4().hex,
            event_type="envelope-completed",
            payload={"event": "envelope-completed", "data": {"envelopeId": uuid.uuid4().hex, "envelopeSummary": {"status": "completed"}}},
            payload_hash=uuid.uuid4().hex,
            signature_valid=True,
            status="RECEIVED",
        ))
        await db.commit()
    await worker.process_pending_docusign_event()
    async with SessionLocal() as db:
        message = await db.get(IntegrationInboxMessage, message_id)
        assert message.status == "RECEIVED"
        assert message.attempts == 1
        assert message.next_attempt_at is not None
        assert message.processed_at is None
