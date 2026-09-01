"""Pins a real, pre-existing incompatibility between the bank-connection
exchange flow and the only concrete bank adapter this repo has.

app/banking.py's exchange_public_token() (added in 283b789, "fix(security):
keep bank credentials outside MoneyBee") requires the adapter to return an
opaque credential_reference pointing into an external credential store, and
503s with BANK_CREDENTIAL_STORE_UNAVAILABLE otherwise - a deliberate,
correctly fail-closed security control. But PlaidAdapter.exchange_public_token
(app/integrations/plaid.py) still returns Plaid's actual API response shape -
{"access_token", "item_id", "request_id"} - which was never updated to match
that contract, and PlaidAdapter.resolve_access_token() is an unconditional
stub. The result: the bank-connection exchange/sync flow cannot function end
to end against the only real adapter this repo has, and nothing exercised
this path before (no prior test referenced exchange_public_token or
BankExchangeInput at all).

This is not something to silently "fix" by, say, encrypting the token into
MoneyBee's own database - that's exactly the design the security-hardening
commit deliberately moved away from. Making bank.live_connection actually
work requires integrating a real external secrets store (AWS Secrets
Manager, Vault, etc.), which is an infrastructure/vendor decision outside
what this repo can make unilaterally. These tests exist so the gap is
pinned down, asserted, and discoverable - not silently broken - until that
decision is made.
"""

import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app import banking, models
from app.config import settings
from app.db import SessionLocal
from app.integrations.base import ProviderError
from app.integrations.plaid import PlaidAdapter
from app.main import app


async def _seed_application() -> models.Application:
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
        await db.refresh(application)
        return application


async def test_the_real_plaid_exchange_response_has_no_credential_reference(monkeypatch):
    """Documents the exact shape mismatch: Plaid's real API response never
    contains the field app/banking.py requires."""
    monkeypatch.setattr(settings, "bank_provider", "plaid")
    monkeypatch.setattr(settings, "plaid_client_id", "test-client-id")
    monkeypatch.setattr(settings, "plaid_secret", "test-secret")

    async def fake_exchange(self, public_token: str) -> dict:
        # This is Plaid's actual /item/public_token/exchange response shape -
        # see PlaidAdapter.exchange_public_token, which returns exactly this.
        return {"access_token": "access-sandbox-fake", "item_id": "item-fake", "request_id": "req-1"}

    monkeypatch.setattr(PlaidAdapter, "exchange_public_token", fake_exchange)

    with TestClient(app):
        application = await _seed_application()
        async with SessionLocal() as db:
            application = await db.merge(application)
            with pytest.raises(HTTPException) as caught:
                await banking.exchange_public_token(db, application, "public-fake-token")
            assert caught.value.status_code == 503
            assert caught.value.detail["code"] == "BANK_CREDENTIAL_STORE_UNAVAILABLE"


async def test_plaid_resolve_access_token_always_raises_until_a_vault_is_integrated():
    """PlaidAdapter.resolve_access_token is an unconditional stub - there is
    no external credential store integrated yet, so any stored
    credential_reference can never actually be resolved back into a usable
    access token. bank.live_connection cannot go live with BANK_PROVIDER=plaid
    until this is replaced with a real vault client."""
    adapter = PlaidAdapter()
    with pytest.raises(ProviderError) as caught:
        await adapter.resolve_access_token("any-reference")
    assert caught.value.provider == "plaid"
