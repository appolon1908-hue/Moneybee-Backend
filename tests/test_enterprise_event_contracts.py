from app.event_contracts import (
    INTERNAL_ACTOR_KEY,
    INTERNAL_SUBJECT_KEY,
    build_event_envelope,
    canonical_event_type,
)


def test_account_provisioned_matches_middleware_contract_shape():
    envelope = build_event_envelope(
        event_id="evt-12345678",
        event_type="codestra.moneybee.account.provisioned",
        aggregate_type="moneybee-user",
        aggregate_id="00000000-0000-0000-0000-000000000001",
        aggregate_version=1,
        tenant_id="00000000-0000-0000-0000-000000000002",
        correlation_id="corr-12345678",
        causation_id="cause-12345678",
        occurred_at="2026-08-27T20:00:00+00:00",
        idempotency_key="idem-12345678",
        schema_version=1,
        delivery_attempt=1,
        payload={
            "user_id": "00000000-0000-0000-0000-000000000001",
            "organization_id": "00000000-0000-0000-0000-000000000002",
            "membership_type": "BORROWER",
            "email": "borrower@example.com",
            "email_verified": True,
            "display_name": "Borrower Example",
            "marketing_consent": False,
            INTERNAL_SUBJECT_KEY: "moneybee-user:00000000-0000-0000-0000-000000000001",
            INTERNAL_ACTOR_KEY: {
                "type": "user",
                "id": "keycloak:subject-123",
            },
        },
    )

    assert envelope["specversion"] == "1.0"
    assert envelope["type"] == "codestra.moneybee.account.provisioned"
    assert envelope["source"] == "urn:codestra:moneybee-backend"
    assert envelope["subject"].startswith("moneybee-user:")
    assert envelope["actor"] == {"type": "user", "id": "keycloak:subject-123"}
    assert INTERNAL_SUBJECT_KEY not in envelope["data"]
    assert INTERNAL_ACTOR_KEY not in envelope["data"]
    assert "aggregate_version" not in envelope["data"]


def test_legacy_events_are_namespaced_under_codestra_moneybee():
    assert canonical_event_type("LeadSubmitted") == "codestra.moneybee.lead.created.v1"
    assert canonical_event_type("offer.accepted.v1") == "codestra.moneybee.offer.accepted.v1"
    assert canonical_event_type("FinanceJournalPosted") == "codestra.moneybee.finance.journal.posted.v1"


def test_pretenant_event_uses_explicit_public_scope_and_service_actor():
    envelope = build_event_envelope(
        event_id="evt-public-1234",
        event_type="LeadSubmitted",
        aggregate_type="lead",
        aggregate_id="00000000-0000-0000-0000-000000000003",
        aggregate_version=None,
        tenant_id=None,
        correlation_id=None,
        causation_id=None,
        occurred_at="2026-08-27T20:00:00+00:00",
        idempotency_key="idem-public-1234",
        payload={"lead_id": "00000000-0000-0000-0000-000000000003"},
    )

    assert envelope["tenant_id"] == "public"
    assert envelope["actor"] == {"type": "service", "id": "moneybee-backend"}
    assert envelope["correlation_id"] == envelope["id"]
    assert envelope["causation_id"] == envelope["id"]
