import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.auth import Principal
from app.portal_schemas import UploadSessionCreate
from app.portal_security import active_tenant, require_borrower, require_lender
from app.upload_service import build_storage_key, validate_upload, verify_uploaded_object


def principal(*, membership_type: str, entity_id: uuid.UUID) -> Principal:
    organization_id = uuid.uuid4()
    return Principal(
        user_id=uuid.uuid4(),
        issuer="https://auth.codestra.co/realms/moneybee",
        subject=f"test-{membership_type.lower()}",
        organization_ids=[organization_id],
        active_organization_id=organization_id,
        roles={membership_type},
        permissions=set(),
        membership_types={membership_type},
        borrower_id=entity_id if membership_type == "BORROWER" else None,
        lender_id=entity_id if membership_type == "LENDER" else None,
        is_active=True,
    )


def upload_payload(**overrides) -> UploadSessionCreate:
    values = {
        "document_type": "BANK_STATEMENT",
        "original_file_name": "statement.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 4096,
        "sha256": "a" * 64,
    }
    values.update(overrides)
    return UploadSessionCreate(**values)


def test_portal_role_helpers_are_fail_closed() -> None:
    borrower_id = uuid.uuid4()
    borrower = principal(membership_type="BORROWER", entity_id=borrower_id)
    assert active_tenant(borrower) == borrower.active_organization_id
    assert require_borrower(borrower) == borrower_id
    with pytest.raises(HTTPException) as exc_info:
        require_lender(borrower)
    assert exc_info.value.status_code == 403


def test_upload_validation_rejects_paths_and_unknown_types() -> None:
    with pytest.raises(HTTPException):
        validate_upload(upload_payload(original_file_name="../../statement.pdf"))
    with pytest.raises(HTTPException):
        validate_upload(upload_payload(mime_type="application/x-executable"))


def test_storage_key_is_quarantine_scoped() -> None:
    tenant_id = uuid.uuid4()
    application_id = uuid.uuid4()
    session_id = uuid.uuid4()
    key = build_storage_key(
        tenant_id=tenant_id,
        application_id=application_id,
        session_id=session_id,
        original_file_name="bank statement (final).pdf",
    )
    assert key.startswith(f"quarantine/{tenant_id}/{application_id}/{session_id}/")
    assert ".." not in key
    assert " " not in key


class FakeS3:
    def head_object(self, **kwargs):
        del kwargs
        return {
            "ContentLength": 4096,
            "ETag": '"etag-1"',
            "Metadata": {
                "sha256": "a" * 64,
                "moneybee-session-id": str(self.session_id),
            },
        }


def test_uploaded_object_requires_matching_integrity_metadata(monkeypatch) -> None:
    session_id = uuid.uuid4()
    fake = FakeS3()
    fake.session_id = session_id
    monkeypatch.setenv("MONEYBEE_DOCUMENT_BUCKET", "test-private-bucket")
    result = verify_uploaded_object(
        storage_key="quarantine/test/document.pdf",
        expected_size=4096,
        expected_sha256="a" * 64,
        expected_session_id=session_id,
        client=fake,
    )
    assert result.etag == "etag-1"
    assert result.size_bytes == 4096
    assert datetime.now(UTC).tzinfo is not None
