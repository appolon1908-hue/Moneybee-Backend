from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.borrower_portal import _application_read, _document_read, _offer_read, _require_borrower


def test_borrower_context_is_required():
    principal = SimpleNamespace(
        borrower_id=None,
        membership_types=set(),
        active_organization_id=uuid4(),
    )
    with pytest.raises(Exception) as exc_info:
        _require_borrower(principal)
    assert getattr(exc_info.value, "status_code", None) == 403


def test_application_projection_is_json_safe_and_allowlisted():
    application = SimpleNamespace(
        id=uuid4(),
        application_number="MB-2026-0001",
        status="DRAFT",
        requested_amount=Decimal("25000.00"),
        created_at=datetime.now(UTC),
        ssn="never-return-this",
    )
    payload = _application_read(application)
    assert payload["id"] == str(application.id)
    assert payload["requested_amount"] == "25000.00"
    assert "ssn" not in payload


def test_offer_projection_does_not_expose_provider_payloads():
    offer = SimpleNamespace(
        id=uuid4(),
        application_id=uuid4(),
        status="PRESENTED",
        amount=Decimal("15000"),
        provider_payload={"secret": "value"},
    )
    payload = _offer_read(offer)
    assert payload["amount"] == "15000"
    assert "provider_payload" not in payload


def test_document_projection_never_exposes_storage_location():
    document = SimpleNamespace(
        id=uuid4(),
        application_id=uuid4(),
        document_type="BANK_STATEMENT",
        status="QUARANTINED",
        storage_key="private/key",
        object_key="private/object",
    )
    payload = _document_read(document)
    assert "storage_key" not in payload
    assert "object_key" not in payload
