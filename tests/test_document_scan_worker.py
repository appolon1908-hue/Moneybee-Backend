import asyncio
import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app import models, worker
from app.config import settings
from app.db import SessionLocal
from app.integrations.base import ProviderError
from app.integrations.base import MalwareScanResult
from app.main import app
from app.integration_models import OperationalException
from sqlalchemy import select


class _FakeStorage:
    def __init__(self, content: bytes):
        self.content = content
        self.deleted_keys: list[str] = []

    async def get_private(self, *, object_key: str) -> bytes:
        return self.content

    async def delete_private(self, *, object_key: str) -> None:
        self.deleted_keys.append(object_key)


class _FailingStorage:
    async def get_private(self, *, object_key: str) -> bytes:
        raise ProviderError("storage", "temporary outage")


class _FakeClamd:
    def __init__(self, response: bytes):
        self.response = response

    async def _handle(self, reader, writer):
        await reader.readexactly(len(b"zINSTREAM\0"))
        while True:
            length = int.from_bytes(await reader.readexactly(4), "big")
            if length == 0:
                break
            await reader.readexactly(length)
        writer.write(self.response)
        await writer.drain()
        writer.close()

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self._server.close()
        await self._server.wait_closed()


async def _seed_quarantined_document(content: bytes = b"harmless content") -> str:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Doc",
            last_name="Scanner",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550177",
            business_name="Document Scan Test Co",
            funding_amount=50000,
            use_of_funds="WORKING_CAPITAL",
            time_in_business_months=24,
            monthly_revenue=50000,
            postal_code="33101",
        )
        db.add(lead)
        await db.flush()
        application = models.Application(
            lead_id=lead.id,
            requested_amount=50000,
            monthly_revenue=50000,
            time_in_business_months=24,
        )
        db.add(application)
        await db.flush()
        document = models.Document(
            application_id=application.id,
            document_type="BANK_STATEMENT",
            original_file_name="statement.pdf",
            mime_type="application/pdf",
            size_bytes=11,
            storage_key=f"documents/{uuid.uuid4().hex}",
            sha256=hashlib.sha256(content).hexdigest(),
            status="QUARANTINED",
            uploaded_by="test-subject",
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
        return str(document.id)


async def test_scan_pending_document_does_nothing_when_scanning_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "malware_scan_provider", "disabled")
    with TestClient(app):
        document_id = await _seed_quarantined_document()
        result = await worker.scan_pending_document()
        assert result is None

        async with SessionLocal() as db:
            document = await db.get(models.Document, uuid.UUID(document_id))
            assert document.status == "QUARANTINED"


async def test_scan_pending_document_marks_a_clean_result(monkeypatch):
    server = _FakeClamd(b"stream: OK\0")
    port = await server.start()
    fake_storage = _FakeStorage(b"harmless content")
    monkeypatch.setattr(settings, "malware_scan_provider", "clamav")
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", port)
    monkeypatch.setattr(worker, "storage_adapter", lambda: fake_storage)

    with TestClient(app):
        document_id = await _seed_quarantined_document(b"harmless content")
        try:
            # Loop until this test's own document is claimed - the worker
            # claims globally-oldest QUARANTINED, and other tests in this
            # module may leave their own behind.
            for _ in range(10):
                processed = await worker.scan_pending_document()
                if processed == document_id:
                    break
        finally:
            await server.stop()

    async with SessionLocal() as db:
        document = await db.get(models.Document, uuid.UUID(document_id))
        assert document.status == "CLEAN"
        assert document.scan_provider == "clamav"
        assert document.scanned_at is not None


async def test_scan_pending_document_rejects_and_deletes_an_infected_file(monkeypatch):
    server = _FakeClamd(b"stream: Eicar-Test-Signature FOUND\0")
    port = await server.start()
    fake_storage = _FakeStorage(b"fake malware bytes")
    monkeypatch.setattr(settings, "malware_scan_provider", "clamav")
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", port)
    monkeypatch.setattr(worker, "storage_adapter", lambda: fake_storage)

    with TestClient(app):
        document_id = await _seed_quarantined_document(b"fake malware bytes")
        try:
            for _ in range(10):
                processed = await worker.scan_pending_document()
                if processed == document_id:
                    break
        finally:
            await server.stop()

    async with SessionLocal() as db:
        document = await db.get(models.Document, uuid.UUID(document_id))
        assert document.status == "REJECTED"
        assert "FOUND" in document.scan_result
    assert fake_storage.deleted_keys


async def test_scan_pending_document_rejects_checksum_mismatch_before_scanning(monkeypatch):
    class ScannerMustNotRun:
        async def scan(self, content: bytes):
            raise AssertionError("checksum-mismatched bytes must not reach the scanner")

    fake_storage = _FakeStorage(b"tampered stored bytes")
    monkeypatch.setattr(settings, "malware_scan_provider", "clamav")
    monkeypatch.setattr(worker, "storage_adapter", lambda: fake_storage)
    monkeypatch.setattr(worker, "malware_scanner", lambda: ScannerMustNotRun())
    with TestClient(app):
        document_id = await _seed_quarantined_document(b"original uploaded bytes")
        assert await worker.scan_pending_document() == document_id

    async with SessionLocal() as db:
        document = await db.get(models.Document, uuid.UUID(document_id))
        assert document.status == "REJECTED"
        assert document.scan_provider == "integrity-check"
        assert document.scan_result == "STORED_DOCUMENT_CHECKSUM_MISMATCH"
        assert document.provider_terminal_at is not None
        exception = await db.scalar(
            select(OperationalException).where(
                OperationalException.fingerprint
                == f"DOCUMENT_CHECKSUM_MISMATCH:{document_id}"
            )
        )
        assert exception is not None


async def test_scan_failure_persists_backoff_and_does_not_starve_another_document(monkeypatch):
    monkeypatch.setattr(settings, "malware_scan_provider", "clamav")
    monkeypatch.setattr(worker, "storage_adapter", lambda: _FailingStorage())
    with TestClient(app):
        first_id = await _seed_quarantined_document(b"safe")
        assert await worker.scan_pending_document() is None
        async with SessionLocal() as db:
            first = await db.get(models.Document, uuid.UUID(first_id))
            assert first.provider_attempt_count == 1
            assert first.provider_last_error == "storage: temporary outage"
            assert first.provider_next_attempt_at is not None
            assert first.provider_terminal_at is None

        server = _FakeClamd(b"stream: OK\0")
        port = await server.start()
        monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
        monkeypatch.setattr(settings, "clamav_port", port)
        monkeypatch.setattr(worker, "storage_adapter", lambda: _FakeStorage(b"safe"))
        second_id = await _seed_quarantined_document(b"safe")
        try:
            processed = await worker.scan_pending_document()
            assert processed == second_id
            async with SessionLocal() as db:
                first = await db.get(models.Document, uuid.UUID(first_id))
                first.provider_next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
                await db.commit()
            assert await worker.scan_pending_document() == first_id
            async with SessionLocal() as db:
                first = await db.get(models.Document, uuid.UUID(first_id))
                assert first.status == "CLEAN"
                assert first.provider_last_error is None
                assert first.provider_next_attempt_at is None
        finally:
            await server.stop()


async def test_repeated_scan_failure_dead_letters_and_survives_worker_restart(monkeypatch):
    monkeypatch.setattr(settings, "malware_scan_provider", "clamav")
    monkeypatch.setattr(worker, "storage_adapter", lambda: _FailingStorage())
    with TestClient(app):
        document_id = await _seed_quarantined_document(b"safe")
        async with SessionLocal() as db:
            document = await db.get(models.Document, uuid.UUID(document_id))
            document.provider_attempt_count = worker.PROVIDER_MAX_ATTEMPTS - 1
            await db.commit()
        assert await worker.scan_pending_document() is None
        async with SessionLocal() as db:
            document = await db.get(models.Document, uuid.UUID(document_id))
            assert document.provider_attempt_count == worker.PROVIDER_MAX_ATTEMPTS
            assert document.provider_terminal_at is not None
            assert document.provider_next_attempt_at is None
            exception = await db.scalar(
                select(OperationalException).where(
                    OperationalException.fingerprint
                    == f"DOCUMENT_SCAN_RETRY_EXHAUSTED:{document_id}"
                )
            )
            assert exception is not None
        monkeypatch.setattr(worker, "WORKER_ID", "replacement-worker")
        assert await worker.scan_pending_document() is None
        async with SessionLocal() as db:
            document = await db.get(models.Document, uuid.UUID(document_id))
            assert document.provider_attempt_count == worker.PROVIDER_MAX_ATTEMPTS


def test_provider_backoff_is_bounded_deterministic_and_increases():
    item_id = uuid.uuid4()
    delays = [worker.provider_retry_delay_seconds(item_id, attempt) for attempt in range(1, 9)]
    assert delays == [worker.provider_retry_delay_seconds(item_id, attempt) for attempt in range(1, 9)]
    assert delays == sorted(delays)
    assert all(2 ** attempt <= delay <= min(3600, 2 ** attempt + 2 ** attempt // 4)
               for attempt, delay in enumerate(delays, 1))


async def test_postgres_concurrent_workers_cannot_claim_the_same_document(monkeypatch):
    if not settings.database_url.startswith("postgresql"):
        import pytest

        pytest.skip("PostgreSQL SKIP LOCKED evidence")

    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingScanner:
        async def scan(self, content: bytes) -> MalwareScanResult:
            started.set()
            await release.wait()
            return MalwareScanResult(provider="fixture", clean=True, signature=None, raw="OK")

    monkeypatch.setattr(settings, "malware_scan_provider", "clamav")
    monkeypatch.setattr(worker, "storage_adapter", lambda: _FakeStorage(b"safe"))
    monkeypatch.setattr(worker, "malware_scanner", lambda: BlockingScanner())
    with TestClient(app):
        document_id = await _seed_quarantined_document(b"safe")
        first = asyncio.create_task(worker.scan_pending_document())
        await asyncio.wait_for(started.wait(), timeout=5)
        second = await worker.scan_pending_document()
        release.set()
        assert await first == document_id
        assert second is None
