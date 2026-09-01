import asyncio
import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app import models, worker
from app.config import settings
from app.db import SessionLocal
from app.main import app


class _FakeStorage:
    def __init__(self, content: bytes):
        self.content = content
        self.deleted_keys: list[str] = []

    async def get_private(self, *, object_key: str) -> bytes:
        return self.content

    async def delete_private(self, *, object_key: str) -> None:
        self.deleted_keys.append(object_key)


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


async def _seed_quarantined_document() -> str:
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
            sha256="0" * 64,
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
        document_id = await _seed_quarantined_document()
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
        document_id = await _seed_quarantined_document()
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
