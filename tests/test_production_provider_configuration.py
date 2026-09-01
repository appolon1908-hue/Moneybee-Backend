import pytest
from pydantic import ValidationError

from app.config import Settings


SECURE_ENVIRONMENT = {
    "app_env": "production",
    "auto_create_schema": False,
    "local_auth_bypass": False,
    "local_identity_enforcement": True,
}


@pytest.mark.parametrize(
    ("provider_settings", "expected_message"),
    [
        (
            {"crm_provider": "generic_http"},
            "Generic HTTP CRM configuration is incomplete",
        ),
        (
            {"kyb_provider": "generic_http"},
            "Generic HTTP KYB configuration is incomplete",
        ),
        (
            {"credit_provider": "generic_http"},
            "Generic HTTP credit configuration is incomplete",
        ),
        (
            {"lender_provider": "generic_http"},
            "Generic HTTP lender configuration is incomplete",
        ),
        (
            {"esign_provider": "docusign"},
            "DocuSign configuration is incomplete",
        ),
    ],
)
def test_enabled_provider_modes_fail_closed_without_required_credentials(
    provider_settings: dict[str, str],
    expected_message: str,
):
    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            **SECURE_ENVIRONMENT,
            **provider_settings,
        )
    assert expected_message in str(caught.value)


@pytest.mark.parametrize(
    "provider_settings",
    [
        {
            "crm_provider": "generic_http",
            "crm_base_url": "https://crm.example.test",
            "crm_api_key": "test-crm-key",
        },
        {
            "kyb_provider": "generic_http",
            "kyb_base_url": "https://kyb.example.test",
            "kyb_api_key": "test-kyb-key",
        },
        {
            "credit_provider": "generic_http",
            "credit_base_url": "https://credit.example.test",
            "credit_api_key": "test-credit-key",
        },
        {
            "lender_provider": "generic_http",
            "lender_base_url": "https://lender.example.test",
            "lender_api_key": "test-lender-key",
        },
        {
            "esign_provider": "docusign",
            "docusign_account_id": "test-account",
            "docusign_access_token": "test-access-token",
            "docusign_template_id": "test-template",
        },
    ],
)
def test_enabled_provider_modes_accept_complete_configuration(
    provider_settings: dict[str, str],
):
    configured = Settings(
        _env_file=None,
        **SECURE_ENVIRONMENT,
        **provider_settings,
    )
    assert configured.app_env == "production"
