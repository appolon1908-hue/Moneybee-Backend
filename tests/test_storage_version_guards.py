from __future__ import annotations

import hashlib
import importlib.util
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from app import models
from app.db import SessionLocal
from app.main import app
from app.portal import borrower
from app.portal import models as portal_models


async def _allow_document_upload(*args, **kwargs):
    return None


async def _seed_upload_session(content: bytes) -> tuple[str, str]:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Versioned",
            last_name="Upload",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550198",
            business_name="Immutable Upload Test LLC",
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
        storage_key = f"documents/{uuid.uuid4().hex}"
        upload = portal_models.DocumentUploadSession(
            application_id=application.id,
            created_by_subject="local-admin",
            document_type="BANK_STATEMENT",
            original_file_name="statement.pdf",
            mime_type="application/pdf",
            size_bytes=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            storage_key=storage_key,
            status="CREATED",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        db.add(upload)
        await db.commit()
        return str(upload.id), storage_key


@pytest.mark.parametrize(
    ("versioning_enabled", "version_id"),
    [(False, "immutable-version-1"), (True, "null"), (True, "   ")],
)
async def test_upload_completion_requires_enabled_non_null_versioning(
    monkeypatch, versioning_enabled: bool, version_id: str
):
    content = b"versioned document"

    class FakeStorage:
        async def bucket_versioning_enabled(self) -> bool:
            return versioning_enabled

        async def head_private(self, *, object_key: str) -> dict:
            return {"ContentLength": len(content), "VersionId": version_id}

    monkeypatch.setattr(borrower.services, "require_capability", _allow_document_upload)
    monkeypatch.setattr(borrower, "S3ObjectStorageAdapter", lambda: FakeStorage())

    with TestClient(app) as client:
        session_id, storage_key = await _seed_upload_session(content)
        response = client.post(
            f"/api/v2/borrower/document-upload-sessions/{session_id}/complete",
            json={
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "DOCUMENT_STORAGE_VERSION_UNAVAILABLE"
    async with SessionLocal() as db:
        upload = await db.get(
            portal_models.DocumentUploadSession, uuid.UUID(session_id)
        )
        document = await db.scalar(
            select(models.Document).where(models.Document.storage_key == storage_key)
        )
        assert upload is not None
        assert upload.status == "CREATED"
        assert document is None


def _load_document_version_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260902_0028_document_storage_version.py"
    )
    spec = importlib.util.spec_from_file_location("document_version_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_document_version_migration_moves_queued_rows_to_reupload(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE documents (
                    id VARCHAR(36) PRIMARY KEY,
                    status VARCHAR(40) NOT NULL,
                    scan_result TEXT,
                    provider_attempt_count INTEGER NOT NULL DEFAULT 0,
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
            text(
                """
                INSERT INTO documents (
                    id,
                    status,
                    provider_attempt_count,
                    provider_last_error,
                    provider_next_attempt_at,
                    provider_lease_owner,
                    provider_lease_expires_at,
                    provider_terminal_at
                ) VALUES (
                    'legacy-document',
                    'QUARANTINED',
                    4,
                    'temporary scanner failure',
                    CURRENT_TIMESTAMP,
                    'old-worker',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        migration = _load_document_version_migration()
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()

        row = connection.execute(
            text(
                """
                SELECT
                    status,
                    storage_version_id,
                    scan_result,
                    provider_attempt_count,
                    provider_last_error,
                    provider_next_attempt_at,
                    provider_lease_owner,
                    provider_lease_expires_at,
                    provider_terminal_at
                FROM documents
                WHERE id = 'legacy-document'
                """
            )
        ).mappings().one()

    assert row["status"] == "REUPLOAD_REQUIRED"
    assert row["storage_version_id"] is None
    assert row["scan_result"] == "IMMUTABLE_STORAGE_VERSION_REQUIRED"
    assert row["provider_attempt_count"] == 0
    assert row["provider_last_error"] == "IMMUTABLE_STORAGE_VERSION_REQUIRED"
    assert row["provider_next_attempt_at"] is None
    assert row["provider_lease_owner"] is None
    assert row["provider_lease_expires_at"] is None
    assert row["provider_terminal_at"] is None
