from types import SimpleNamespace

import pytest

from app.webhook_worker import (
    ProviderTranslatorNotRegistered,
    clear_provider_handlers,
    register_provider_handler,
    require_provider_handler,
    resolve_provider_handler,
)


@pytest.fixture(autouse=True)
def reset_registry():
    clear_provider_handlers()
    yield
    clear_provider_handlers()


def test_exact_provider_event_handler_is_resolved():
    def handler(db, receipt):
        return None

    register_provider_handler("plaid", "TRANSACTIONS_UPDATED", handler)
    assert resolve_provider_handler("PLAID", "TRANSACTIONS_UPDATED") is handler


def test_provider_wildcard_handler_is_explicitly_supported():
    def handler(db, receipt):
        return None

    register_provider_handler("middesk", "*", handler)
    assert resolve_provider_handler("middesk", "BUSINESS_UPDATED") is handler


def test_duplicate_registration_is_rejected():
    def handler(db, receipt):
        return None

    register_provider_handler("experian", "REPORT_READY", handler)
    with pytest.raises(ValueError):
        register_provider_handler("experian", "REPORT_READY", handler)


def test_unregistered_translator_fails_closed():
    with pytest.raises(ProviderTranslatorNotRegistered):
        require_provider_handler("lender", "APPROVED")
