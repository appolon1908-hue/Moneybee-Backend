from app.core.config import Settings


def test_production_sensitive_capabilities_default_disabled() -> None:
    capabilities = Settings(_env_file=None).capabilities()
    assert capabilities == {
        "credit.live_pull": False,
        "lenders.live_submission": False,
        "esign.live_send": False,
        "funding.live_confirmation": False,
        "payments": False,
        "payouts": False,
    }
