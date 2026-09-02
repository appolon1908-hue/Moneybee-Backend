import httpx
import pytest

from app.integrations.base import ProviderError, UnknownOutcomeError
from app.integrations.http import provider_request


@pytest.mark.asyncio
async def test_read_request_uses_bounded_retry(monkeypatch):
    attempts = 0

    async def request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("unavailable")
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    monkeypatch.setattr("app.integrations.http.asyncio.sleep", lambda *_: _noop())

    assert await provider_request(
        provider="example", method="GET", url="https://provider.invalid/status", retries=1
    ) == {"ok": True}
    assert attempts == 2


@pytest.mark.asyncio
async def test_ambiguous_post_is_not_blindly_retried(monkeypatch):
    attempts = 0

    async def request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("response lost")

    monkeypatch.setattr(httpx.AsyncClient, "request", request)

    with pytest.raises(UnknownOutcomeError):
        await provider_request(
            provider="payments",
            method="POST",
            url="https://provider.invalid/payout",
            retries=3,
        )
    assert attempts == 1


@pytest.mark.asyncio
async def test_idempotent_post_retries_with_key(monkeypatch):
    attempts = 0
    captured_headers = []

    async def request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        captured_headers.append(kwargs["headers"])
        if attempts == 1:
            raise httpx.ConnectError("unavailable")
        return httpx.Response(202, json={"id": "operation-1"})

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    monkeypatch.setattr("app.integrations.http.asyncio.sleep", lambda *_: _noop())

    result = await provider_request(
        provider="lender",
        method="POST",
        url="https://provider.invalid/applications",
        retries=1,
        idempotency_key="operation-1",
    )
    assert result == {"id": "operation-1"}
    assert attempts == 2
    assert captured_headers == [
        {"Idempotency-Key": "operation-1"},
        {"Idempotency-Key": "operation-1"},
    ]


@pytest.mark.asyncio
async def test_failed_read_is_dependency_error(monkeypatch):
    async def request(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ProviderError) as caught:
        await provider_request(
            provider="example", method="GET", url="https://provider.invalid", retries=0
        )
    assert not isinstance(caught.value, UnknownOutcomeError)


async def _noop():
    return None
