from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"Expected exactly one marker in {path}; found {count}: {old[:120]!r}"
        )
    write(path, text.replace(old, new, 1))


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n\n" + addition.strip() + "\n")


def patch_decline_draft_contract() -> None:
    replace_once(
        "app/admin_routes.py",
        '''    if contract is not None and contract.status == "SENT":
        if not contract.external_envelope_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "CONTRACT_VOID_RECONCILIATION_REQUIRED"},
            )
        await ensure_provider_void_confirmed(
            db, contract, reason=payload.reason, adapter=esign_adapter()
        )
        services.transition_contract(db, contract, "VOIDED", user, reason=payload.reason)
    await services.transition_funding(db, funding, "DECLINED", user, reason=payload.reason)
''',
        '''    if contract is not None:
        if contract.status == "SENT":
            if not contract.external_envelope_id:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "CONTRACT_VOID_RECONCILIATION_REQUIRED"},
                )
            await ensure_provider_void_confirmed(
                db, contract, reason=payload.reason, adapter=esign_adapter()
            )
            services.transition_contract(
                db, contract, "VOIDED", user, reason=payload.reason
            )
        elif contract.status == "DRAFT":
            # A denied deal must not leave an envelope eligible for a later
            # worker send. This transition is atomic with the funding decline.
            services.transition_contract(
                db, contract, "VOIDED", user, reason=payload.reason
            )
    await services.transition_funding(db, funding, "DECLINED", user, reason=payload.reason)
''',
    )


def patch_storage_version_guards() -> None:
    replace_once(
        "app/integrations/storage.py",
        '''    async def head_private(self, *, object_key: str) -> dict:
        client = self._client()
        try:
            return await asyncio.to_thread(
                client.head_object,
                Bucket=settings.object_storage_bucket,
                Key=object_key,
            )
        except Exception as exc:
            raise ProviderError("s3", "Uploaded object could not be verified") from exc

    async def presigned_download(
''',
        '''    async def head_private(self, *, object_key: str) -> dict:
        client = self._client()
        try:
            return await asyncio.to_thread(
                client.head_object,
                Bucket=settings.object_storage_bucket,
                Key=object_key,
            )
        except Exception as exc:
            raise ProviderError("s3", "Uploaded object could not be verified") from exc

    async def bucket_versioning_enabled(self) -> bool:
        """Return true only when the provider confirms bucket versioning is enabled."""
        client = self._client()
        try:
            response = await asyncio.to_thread(
                client.get_bucket_versioning,
                Bucket=settings.object_storage_bucket,
            )
        except Exception as exc:
            raise ProviderError(
                "s3", "Bucket versioning status could not be verified"
            ) from exc
        return str(response.get("Status") or "").strip().lower() == "enabled"

    async def presigned_download(
''',
    )
    replace_once(
        "app/portal/borrower.py",
        '''    adapter = S3ObjectStorageAdapter()
    try:
        metadata = await adapter.head_private(object_key=item.storage_key)
    except ProviderError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DOCUMENT_UPLOAD_NOT_FOUND", "message": "The uploaded object could not be verified."},
        ) from exc
''',
        '''    adapter = S3ObjectStorageAdapter()
    try:
        versioning_enabled = await adapter.bucket_versioning_enabled()
        metadata = await adapter.head_private(object_key=item.storage_key)
    except ProviderError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_STORAGE_VERSIONING_UNVERIFIED",
                "message": "Immutable object-storage versioning could not be verified.",
            },
        ) from exc
    if not versioning_enabled:
        problem(
            "DOCUMENT_STORAGE_VERSIONING_REQUIRED",
            "The object-storage bucket must have versioning enabled.",
            409,
        )
''',
    )
    replace_once(
        "app/portal/borrower.py",
        '''    version_id = str(metadata.get("VersionId") or "").strip()
    if not version_id:
        problem(
            "DOCUMENT_STORAGE_VERSION_UNAVAILABLE",
            "The uploaded object is not protected by immutable storage versioning.",
            409,
        )
''',
        '''    version_id = str(metadata.get("VersionId") or "").strip()
    if not version_id or version_id.lower() == "null":
        problem(
            "DOCUMENT_STORAGE_VERSION_UNAVAILABLE",
            "The uploaded object is not protected by an immutable storage version.",
            409,
        )
''',
    )


def patch_document_migration() -> None:
    replace_once(
        "migrations/versions/20260902_0028_document_storage_version.py",
        '''def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("storage_version_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
''',
        '''def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("storage_version_id", sa.String(length=255), nullable=True))

    # Pre-existing queued uploads cannot be proven immutable after this schema
    # upgrade. Move them to an explicit recoverable re-upload state rather than
    # allowing the scan worker to retry and eventually terminalize them.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE documents
               SET status = 'REUPLOAD_REQUIRED',
                   scan_provider = 'migration',
                   scan_result = 'IMMUTABLE_STORAGE_VERSION_REQUIRED',
                   provider_last_error = 'immutable stored-object version missing after upgrade',
                   provider_next_attempt_at = NULL,
                   provider_lease_owner = NULL,
                   provider_lease_expires_at = NULL,
                   provider_terminal_at = NULL
             WHERE status = 'QUARANTINED'
               AND storage_version_id IS NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
''',
    )
    replace_once(
        "migrations/versions/20260902_0028_document_storage_version.py",
        '''    if protected is not None:
        raise RuntimeError("Downgrade would discard immutable document-version evidence")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("storage_version_id")
''',
        '''    if protected is not None:
        raise RuntimeError("Downgrade would discard immutable document-version evidence")
    bind.execute(
        sa.text(
            """
            UPDATE documents
               SET status = 'QUARANTINED',
                   scan_provider = NULL,
                   scan_result = NULL,
                   provider_last_error = NULL
             WHERE status = 'REUPLOAD_REQUIRED'
               AND scan_result = 'IMMUTABLE_STORAGE_VERSION_REQUIRED'
            """
        )
    )
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("storage_version_id")
''',
    )


def patch_worker() -> None:
    replace_once(
        "app/worker.py",
        '''from app.models import Contract, Document, Funding, IntegrationEvent, Owner, OutboxEvent, OutboxStatus
''',
        '''from app.models import (
    Application,
    ApplicationStatus,
    Contract,
    Document,
    Funding,
    IntegrationEvent,
    Owner,
    OutboxEvent,
    OutboxStatus,
)
''',
    )
    replace_once(
        "app/worker.py",
        '''    transition_contract,
    transition_funding,
)
''',
        '''    transition_application,
    transition_contract,
    transition_funding,
)
''',
    )
    replace_once(
        "app/worker.py",
        '''        _lease_provider_item(contract, now)
        signer = await db.scalar(
''',
        '''        _lease_provider_item(contract, now)
        application = await db.scalar(
            select(Application)
            .where(Application.id == contract.application_id)
            .with_for_update()
        )
        if application is None:
            _provider_failed(
                contract,
                ProviderError("moneybee", "contract application is missing"),
                datetime.now(UTC),
            )
            return None
        if application.status in {
            ApplicationStatus.DECLINED,
            ApplicationStatus.CANCELLED,
            ApplicationStatus.EXPIRED,
            ApplicationStatus.WITHDRAWN,
        }:
            transition_contract(
                db,
                contract,
                "VOIDED",
                SYSTEM_PRINCIPAL,
                reason=f"Application is terminal: {application.status.value}",
            )
            _provider_succeeded(contract)
            return str(contract.id)
        if application.status not in {
            ApplicationStatus.CONDITIONS_COMPLETE,
            ApplicationStatus.CONTRACT_READY,
        }:
            _provider_failed(
                contract,
                ProviderError(
                    "moneybee",
                    f"application is not ready for contract send: {application.status.value}",
                ),
                datetime.now(UTC),
            )
            return None
        signer = await db.scalar(
''',
    )
    replace_once(
        "app/worker.py",
        '''        envelope_id = str(
            result.get("envelopeId") or result.get("envelope_id") or ""
        ) or None
        if envelope_id is None:
''',
        '''        envelope_id = str(
            result.get("envelopeId") or result.get("envelope_id") or ""
        ).strip()
        if not envelope_id:
''',
    )
    replace_once(
        "app/worker.py",
        '''        contract.provider = "docusign"
        contract.external_envelope_id = envelope_id
        transition_contract(db, contract, "SENT", SYSTEM_PRINCIPAL)
        _provider_succeeded(contract)
''',
        '''        contract.provider = "docusign"
        contract.external_envelope_id = envelope_id
        transition_contract(db, contract, "SENT", SYSTEM_PRINCIPAL)
        if application.status == ApplicationStatus.CONDITIONS_COMPLETE:
            transition_application(
                db,
                application,
                ApplicationStatus.CONTRACT_READY,
                SYSTEM_PRINCIPAL,
                reason="E-sign envelope prepared",
            )
        if application.status == ApplicationStatus.CONTRACT_READY:
            transition_application(
                db,
                application,
                ApplicationStatus.CONTRACT_SENT,
                SYSTEM_PRINCIPAL,
                reason="E-sign envelope sent",
            )
        _provider_succeeded(contract)
''',
    )
    replace_once(
        "app/worker.py",
        '''        if document is None:
            return None
        _lease_provider_item(document, now)
        try:
            if not document.storage_version_id:
                raise ProviderError("s3", "immutable stored-object version is missing")
            content = await storage_adapter().get_private(
''',
        '''        if document is None:
            return None
        version_id = str(document.storage_version_id or "").strip()
        if not version_id or version_id.lower() == "null":
            document.status = "REUPLOAD_REQUIRED"
            document.scan_provider = "migration"
            document.scan_result = "IMMUTABLE_STORAGE_VERSION_REQUIRED"
            document.provider_last_error = "immutable stored-object version is missing"
            document.provider_next_attempt_at = None
            document.provider_lease_owner = None
            document.provider_lease_expires_at = None
            document.provider_terminal_at = None
            db.add(
                OperationalException(
                    fingerprint=f"DOCUMENT_REUPLOAD_REQUIRED:{document.id}",
                    code="DOCUMENT_REUPLOAD_REQUIRED",
                    severity="HIGH",
                    resource_type="document",
                    resource_id=str(document.id),
                    retry_action="REUPLOAD_DOCUMENT_WITH_VERSIONING_ENABLED",
                    comments=[],
                )
            )
            return str(document.id)
        _lease_provider_item(document, now)
        try:
            content = await storage_adapter().get_private(
''',
    )
    replace_once(
        "app/worker.py",
        '''                version_id=document.storage_version_id,
''',
        '''                version_id=version_id,
''',
    )


CONTRACT_TESTS = r'''
async def test_declining_funding_voids_draft_contract_before_worker_send(monkeypatch):
    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = _prepare_matched_submission(client)
        _create_and_accept_offer(client, application_id, submission_id, lender_id, program_id)
        async with SessionLocal() as db:
            funding = await db.scalar(
                select(models.Funding).where(
                    models.Funding.application_id == uuid.UUID(application_id)
                )
            )
            contract = await db.scalar(
                select(models.Contract).where(
                    models.Contract.application_id == uuid.UUID(application_id)
                )
            )
            funding_id = str(funding.id)
            contract_id = contract.id

        response = client.post(
            f"/api/v2/admin/fundings/{funding_id}/decline",
            json={"reason": "Applicant withdrew before signature."},
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "DECLINED"

    async with SessionLocal() as db:
        contract = await db.get(models.Contract, contract_id)
        assert contract.status == "VOIDED"
        remaining = list(
            (
                await db.scalars(
                    select(models.Contract).where(models.Contract.status == "DRAFT")
                )
            ).all()
        )
        for item in remaining:
            item.status = "VOIDED"
        await db.commit()

    class MustNotSend:
        async def send_envelope(self, **kwargs):
            raise AssertionError("a denied draft contract must never be sent")

    monkeypatch.setattr(worker, "esign_live_send_enabled", lambda: True)
    monkeypatch.setattr(worker, "esign_adapter", lambda: MustNotSend())
    assert await worker.send_pending_contract_envelope() is None


async def test_successful_envelope_send_strips_id_and_advances_application(monkeypatch):
    class SuccessfulESign:
        async def send_envelope(self, **kwargs):
            return {"envelopeId": "  envelope-normalized-123  "}

    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = _prepare_matched_submission(client)
        _create_and_accept_offer(client, application_id, submission_id, lender_id, program_id)
        contract_id = client.get(
            f"/api/v2/applications/{application_id}/contract"
        ).json()["id"]

    async with SessionLocal() as db:
        drafts = list(
            (
                await db.scalars(
                    select(models.Contract).where(models.Contract.status == "DRAFT")
                )
            ).all()
        )
        for item in drafts:
            if item.id != uuid.UUID(contract_id):
                item.status = "VOIDED"
        await db.commit()

    monkeypatch.setattr(worker, "esign_live_send_enabled", lambda: True)
    monkeypatch.setattr(worker, "esign_adapter", lambda: SuccessfulESign())
    assert await worker.send_pending_contract_envelope() == contract_id

    async with SessionLocal() as db:
        contract = await db.get(models.Contract, uuid.UUID(contract_id))
        application = await db.get(models.Application, uuid.UUID(application_id))
        assert contract.status == "SENT"
        assert contract.external_envelope_id == "envelope-normalized-123"
        assert application.status == models.ApplicationStatus.CONTRACT_SENT
        history = list(
            (
                await db.scalars(
                    select(models.ApplicationStatusHistory).where(
                        models.ApplicationStatusHistory.application_id
                        == uuid.UUID(application_id)
                    )
                )
            ).all()
        )
        assert any(item.to_status == "CONTRACT_SENT" for item in history)


async def test_whitespace_envelope_identifier_never_marks_contract_sent(monkeypatch):
    class BlankIdentifierESign:
        async def send_envelope(self, **kwargs):
            return {"envelopeId": "   "}

    with TestClient(app) as client:
        application_id, submission_id, lender_id, program_id = _prepare_matched_submission(client)
        _create_and_accept_offer(client, application_id, submission_id, lender_id, program_id)
        contract_id = client.get(
            f"/api/v2/applications/{application_id}/contract"
        ).json()["id"]

    async with SessionLocal() as db:
        drafts = list(
            (
                await db.scalars(
                    select(models.Contract).where(models.Contract.status == "DRAFT")
                )
            ).all()
        )
        for item in drafts:
            if item.id != uuid.UUID(contract_id):
                item.status = "VOIDED"
        await db.commit()

    monkeypatch.setattr(worker, "esign_live_send_enabled", lambda: True)
    monkeypatch.setattr(worker, "esign_adapter", lambda: BlankIdentifierESign())
    assert await worker.send_pending_contract_envelope() is None

    async with SessionLocal() as db:
        contract = await db.get(models.Contract, uuid.UUID(contract_id))
        application = await db.get(models.Application, uuid.UUID(application_id))
        assert contract.status == "DRAFT"
        assert contract.external_envelope_id is None
        assert "identifier" in contract.provider_last_error
        assert application.status != models.ApplicationStatus.CONTRACT_SENT
'''


STORAGE_TESTS = r'''import importlib.util
import os
import uuid
from pathlib import Path

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.main import app
from app.portal import models as portal_models
from app.portal import borrower


async def _seed_upload_session() -> tuple[str, str]:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Version",
            last_name="Guard",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550123",
            business_name="Version Guard LLC",
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
            requested_amount=25000,
            monthly_revenue=30000,
            time_in_business_months=24,
        )
        db.add(application)
        await db.flush()
        item = portal_models.DocumentUploadSession(
            application_id=application.id,
            created_by_subject="test-subject",
            document_type="BANK_STATEMENT",
            original_file_name="statement.pdf",
            mime_type="application/pdf",
            size_bytes=11,
            expected_sha256="a" * 64,
            storage_key=f"documents/{uuid.uuid4().hex}",
            status="CREATED",
            expires_at=models.utcnow().replace(year=models.utcnow().year + 1),
        )
        db.add(item)
        await db.commit()
        return str(item.id), str(application.id)


@pytest.mark.parametrize(
    ("versioning_enabled", "version_id", "expected_code"),
    [
        (False, "version-1", "DOCUMENT_STORAGE_VERSIONING_REQUIRED"),
        (True, "null", "DOCUMENT_STORAGE_VERSION_UNAVAILABLE"),
        (True, "   ", "DOCUMENT_STORAGE_VERSION_UNAVAILABLE"),
    ],
)
async def test_upload_completion_requires_enabled_versioning_and_real_version_id(
    monkeypatch, versioning_enabled, version_id, expected_code
):
    class FakeStorage:
        async def bucket_versioning_enabled(self):
            return versioning_enabled

        async def head_private(self, *, object_key):
            return {"ContentLength": 11, "VersionId": version_id}

    async def capability_enabled(*args, **kwargs):
        return object()

    monkeypatch.setattr(borrower.services, "require_capability", capability_enabled)
    monkeypatch.setattr(borrower, "S3ObjectStorageAdapter", lambda: FakeStorage())
    session_id, _ = await _seed_upload_session()

    with TestClient(app) as client:
        response = client.post(
            f"/api/v2/borrower/document-upload-sessions/{session_id}/complete",
            json={"size_bytes": 11, "sha256": "a" * 64},
        )

    assert response.status_code == 409
    assert response.json()["code"] == expected_code


def test_migration_moves_unversioned_quarantined_documents_to_reupload_state(tmp_path):
    database = tmp_path / "migration.db"
    engine = sa.create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE documents (
                    id VARCHAR(36) PRIMARY KEY,
                    status VARCHAR(40) NOT NULL,
                    scan_provider VARCHAR(40),
                    scan_result TEXT,
                    provider_last_error TEXT,
                    provider_next_attempt_at DATETIME,
                    provider_lease_owner VARCHAR(160),
                    provider_lease_expires_at DATETIME,
                    provider_terminal_at DATETIME
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO documents (id, status)
                VALUES ('queued', 'QUARANTINED'), ('clean', 'CLEAN')
                """
            )
        )

        class Batch:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def add_column(self, column):
                connection.execute(
                    sa.text(
                        "ALTER TABLE documents ADD COLUMN "
                        "storage_version_id VARCHAR(255)"
                    )
                )

            def drop_column(self, name):
                connection.execute(
                    sa.text("ALTER TABLE documents DROP COLUMN storage_version_id")
                )

        class FakeOp:
            def batch_alter_table(self, name):
                assert name == "documents"
                return Batch()

            def get_bind(self):
                return connection

        migration_path = (
            Path(__file__).resolve().parents[1]
            / "migrations/versions/20260902_0028_document_storage_version.py"
        )
        spec = importlib.util.spec_from_file_location("migration_0028", migration_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        module.op = FakeOp()
        module.upgrade()

        queued = connection.execute(
            sa.text(
                """
                SELECT status, scan_result, provider_terminal_at
                  FROM documents
                 WHERE id = 'queued'
                """
            )
        ).mappings().one()
        clean = connection.execute(
            sa.text("SELECT status FROM documents WHERE id = 'clean'")
        ).scalar_one()

    assert queued["status"] == "REUPLOAD_REQUIRED"
    assert queued["scan_result"] == "IMMUTABLE_STORAGE_VERSION_REQUIRED"
    assert queued["provider_terminal_at"] is None
    assert clean == "CLEAN"
'''


DOCUMENT_SCAN_TEST = r'''
async def test_unversioned_quarantined_document_moves_to_reupload_required(monkeypatch):
    monkeypatch.setattr(settings, "malware_scan_provider", "clamav")
    with TestClient(app):
        document_id = await _seed_quarantined_document(b"safe")
        async with SessionLocal() as db:
            document = await db.get(models.Document, uuid.UUID(document_id))
            document.storage_version_id = "null"
            await db.commit()

        assert await worker.scan_pending_document() == document_id

    async with SessionLocal() as db:
        document = await db.get(models.Document, uuid.UUID(document_id))
        assert document.status == "REUPLOAD_REQUIRED"
        assert document.scan_result == "IMMUTABLE_STORAGE_VERSION_REQUIRED"
        assert document.provider_terminal_at is None
        exception = await db.scalar(
            select(OperationalException).where(
                OperationalException.fingerprint
                == f"DOCUMENT_REUPLOAD_REQUIRED:{document_id}"
            )
        )
        assert exception is not None
'''


def add_tests_and_evidence() -> None:
    append_once(
        "tests/test_contract_engine.py",
        "test_declining_funding_voids_draft_contract_before_worker_send",
        CONTRACT_TESTS,
    )
    write("tests/test_storage_version_guards.py", STORAGE_TESTS)
    append_once(
        "tests/test_document_scan_worker.py",
        "test_unversioned_quarantined_document_moves_to_reupload_required",
        DOCUMENT_SCAN_TEST,
    )
    write(
        "docs/reviews/PR42_FINAL_EXACT_HEAD_REMEDIATION.md",
        """# PR #42 final exact-head remediation

This repository-only repair closes five exact-head review findings:

1. Funding decline atomically voids a draft contract.
2. Upload completion requires confirmed enabled bucket versioning and rejects
   blank or `null` S3 version identifiers.
3. Migration `20260902_0028` moves pre-existing unversioned quarantined
   documents to the recoverable `REUPLOAD_REQUIRED` state.
4. Successful e-sign send atomically advances the application to
   `CONTRACT_SENT`.
5. Whitespace-only envelope identifiers are rejected.

Regression coverage is in `tests/test_contract_engine.py`,
`tests/test_document_scan_worker.py`, and
`tests/test_storage_version_guards.py`.

This change does not deploy, contact a server, modify SSH, add credentials, or
enable any external effect.
""",
    )


def main() -> None:
    patch_decline_draft_contract()
    patch_storage_version_guards()
    patch_document_migration()
    patch_worker()
    add_tests_and_evidence()
    print("PR42_FINAL_REVIEW_FIXES=APPLIED")


if __name__ == "__main__":
    main()
