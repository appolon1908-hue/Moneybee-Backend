from app.core.config import settings


def test_financial_capabilities_default_disabled() -> None:
    assert settings.credit_live_pull is False
    assert settings.lenders_live_submission is False
    assert settings.esign_live_send is False
    assert settings.funding_live_confirmation is False
    assert settings.payments_enabled is False
    assert settings.payouts_enabled is False
