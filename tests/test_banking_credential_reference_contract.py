"""Bank access tokens are never persisted in MoneyBee's own database - only
an opaque reference into an external credential store (Vault). This used to
be broken: app/banking.py required adapters return a credential_reference,
but PlaidAdapter.exchange_public_token returned Plaid's real access_token
with no such field, and PlaidAdapter.resolve_access_token was an
unconditional stub - the exchange/sync flow always 503'd regardless of
provider configuration, and nothing tested this path.

Fixed by moving credential storage out of the per-provider adapter and into
app/banking.py's orchestration, via a CredentialStore Protocol
(app/integrations/base.py) backed by self-hosted HashiCorp Vault's KV v2
API (app/integrations/vault.py). PlaidAdapter now only talks to Plaid;
app/banking.py calls credential_store().store()/.resolve() around it.

These tests prove the fixed flow end to end: exchange stores the token via
the credential store (never the raw token in the database), sync resolves
it back correctly, the whole thing still fails closed with
BANK_CREDENTIAL_STORE_UNAVAILABLE when no credential store is configured
(the default), and VaultCredentialStore's KV v2 request/response handling
is correct.
"""

import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app import banking, models
from app.config import settings
from app.db import SessionLocal
from app.integrations.base import ProviderError
from app.integrations.plaid import PlaidAdapter
from app.integrations.vault import VaultCredentialStore
from app.main import app


async def _seed_application() -> uuid.UUID:
    async with SessionLocal() as db:
        lead = models.Lead(
            first_name="Bank",
            last_name="Contract",
            email=f"{uuid.uuid4().hex}@example.com",
            phone="+15555550112",
            business_name="Bank Contract Test Co",
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
        await db.commit()
        return application.id


class _FakeVault:
    """An in-memory stand-in for a real Vault server, keyed the same way
    VaultCredentialStore.store()'s real references are - proves
    app/banking.py's orchestration is correct independent of Vault's own
    wire format, which is covered separately below."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def store(self, secret: str) -> str:
        reference = f"moneybee/bank-credentials/{uuid.uuid4()}"
        self._values[reference] = secret
        return reference

    async def resolve(self, reference: str) -> str:
        try:
            return self._values[reference]
        except KeyError as exc:
            raise ProviderError("vault", "Credential reference not found") from exc


def _enable_plaid_and_vault(monkeypatch, fake_vault: _FakeVault) -> None:
    monkeypatch.setattr(settings, "bank_provider", "plaid")
    monkeypatch.setattr(settings, "plaid_client_id", "test-client-id")
    monkeypatch.setattr(settings, "plaid_secret", "test-secret")
    monkeypatch.setattr(settings, "bank_credential_store_provider", "vault")
    monkeypatch.setattr(banking, "credential_store", lambda: fake_vault)


async def test_exchange_public_token_never_persists_the_raw_access_token(monkeypatch):
    fake_vault = _FakeVault()
    _enable_plaid_and_vault(monkeypatch, fake_vault)

    async def fake_exchange(self, public_token: str) -> dict:
        return {"access_token": "access-sandbox-real-secret", "item_id": "item-1", "request_id": "req-1"}

    monkeypatch.setattr(PlaidAdapter, "exchange_public_token", fake_exchange)

    with TestClient(app):
        application_id = await _seed_application()
        async with SessionLocal() as db:
            application = await db.get(models.Application, application_id)
            connection = await banking.exchange_public_token(db, application, "public-fake-token")
            await db.commit()

            state = await db.scalar(
                select(models.BankProviderState).where(
                    models.BankProviderState.connection_id == connection.id
                )
            )
            assert state is not None
            assert state.credential_reference != "access-sandbox-real-secret"
            assert state.credential_reference.startswith("moneybee/bank-credentials/")
            assert await fake_vault.resolve(state.credential_reference) == (
                "access-sandbox-real-secret"
            )


async def test_sync_bank_resolves_the_access_token_through_the_credential_store(monkeypatch):
    fake_vault = _FakeVault()
    _enable_plaid_and_vault(monkeypatch, fake_vault)

    async def fake_exchange(self, public_token: str) -> dict:
        return {"access_token": "access-sandbox-real-secret", "item_id": "item-2", "request_id": "req-2"}

    resolved_tokens: list[str] = []

    async def fake_get_accounts(self, access_token: str) -> dict:
        resolved_tokens.append(access_token)
        return {"accounts": []}

    async def fake_sync_transactions(self, access_token: str, cursor: str | None) -> dict:
        resolved_tokens.append(access_token)
        return {"added": [], "modified": [], "removed": [], "next_cursor": "cursor-1"}

    monkeypatch.setattr(PlaidAdapter, "exchange_public_token", fake_exchange)
    monkeypatch.setattr(PlaidAdapter, "get_accounts", fake_get_accounts)
    monkeypatch.setattr(PlaidAdapter, "sync_transactions", fake_sync_transactions)

    with TestClient(app):
        application_id = await _seed_application()
        async with SessionLocal() as db:
            application = await db.get(models.Application, application_id)
            await banking.exchange_public_token(db, application, "public-fake-token")
            await db.commit()

        async with SessionLocal() as db:
            application = await db.get(models.Application, application_id)
            await banking.sync_bank(db, application)

    assert resolved_tokens == ["access-sandbox-real-secret", "access-sandbox-real-secret"]


async def test_exchange_public_token_fails_closed_when_no_credential_store_is_configured(monkeypatch):
    # bank_credential_store_provider defaults to "disabled" - the
    # credential_store() selector raises ProviderError, which
    # app/banking.py must turn into the standing 503 rather than ever
    # falling back to persisting the raw token.
    monkeypatch.setattr(settings, "bank_provider", "plaid")
    monkeypatch.setattr(settings, "plaid_client_id", "test-client-id")
    monkeypatch.setattr(settings, "plaid_secret", "test-secret")

    async def fake_exchange(self, public_token: str) -> dict:
        return {"access_token": "access-sandbox-real-secret", "item_id": "item-3", "request_id": "req-3"}

    monkeypatch.setattr(PlaidAdapter, "exchange_public_token", fake_exchange)

    with TestClient(app):
        application_id = await _seed_application()
        async with SessionLocal() as db:
            application = await db.get(models.Application, application_id)
            with pytest.raises(HTTPException) as caught:
                await banking.exchange_public_token(db, application, "public-fake-token")
            assert caught.value.status_code == 503
            assert caught.value.detail["code"] == "BANK_CREDENTIAL_STORE_UNAVAILABLE"


# --- VaultCredentialStore's own KV v2 wire format --------------------------


async def test_vault_credential_store_writes_kv_v2_shape_and_reads_it_back(monkeypatch):
    monkeypatch.setattr(settings, "vault_addr", "https://vault.internal:8200")
    monkeypatch.setattr(settings, "vault_token", "s.test-token")
    monkeypatch.setattr(settings, "vault_mount", "secret")
    monkeypatch.setattr(settings, "vault_path_prefix", "moneybee/bank-credentials")

    written: dict[str, dict] = {}

    async def fake_provider_request(*, provider, method, url, headers=None, json=None, retries=2):
        assert provider == "vault"
        assert headers == {"X-Vault-Token": "s.test-token"}
        if method == "POST":
            assert url.startswith(
                "https://vault.internal:8200/v1/secret/data/moneybee/bank-credentials/"
            )
            assert json == {"data": {"value": "the-secret-token"}}
            written["path"] = url
            written["value"] = json["data"]["value"]
            return {"data": {"version": 1}}
        assert method == "GET"
        assert url == written["path"]
        return {"data": {"data": {"value": written["value"]}, "metadata": {"version": 1}}}

    import app.integrations.vault as vault_module

    monkeypatch.setattr(vault_module, "provider_request", fake_provider_request)

    store = VaultCredentialStore()
    reference = await store.store("the-secret-token")
    assert reference.startswith("moneybee/bank-credentials/")
    assert await store.resolve(reference) == "the-secret-token"


async def test_vault_credential_store_raises_on_a_missing_reference(monkeypatch):
    monkeypatch.setattr(settings, "vault_addr", "https://vault.internal:8200")
    monkeypatch.setattr(settings, "vault_token", "s.test-token")

    async def fake_provider_request(**kwargs):
        raise ProviderError("vault", "not found", status_code=404)

    import app.integrations.vault as vault_module

    monkeypatch.setattr(vault_module, "provider_request", fake_provider_request)

    store = VaultCredentialStore()
    with pytest.raises(ProviderError):
        await store.resolve("moneybee/bank-credentials/does-not-exist")


def test_vault_credential_store_requires_configuration():
    store = VaultCredentialStore()
    with pytest.raises(ProviderError):
        store._headers()  # noqa: SLF001
