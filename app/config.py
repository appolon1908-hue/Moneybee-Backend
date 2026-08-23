from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "dev", "staging", "production"] = "local"
    database_url: str = "sqlite+aiosqlite:///./moneybee.db"
    redis_url: str = "redis://localhost:6379/0"
    auto_create_schema: bool = True
    local_auth_bypass: bool = True
    cors_origins_csv: str = (
        "http://localhost:5173,http://localhost:5174,"
        "http://localhost:5175,http://localhost:5176"
    )
    oidc_issuer: str = "https://auth.codestra.co/realms/codestra"
    oidc_audience: str = "moneybee-api"
    oidc_jwks_url: str = (
        "https://auth.codestra.co/realms/codestra/protocol/openid-connect/certs"
    )
    codestra_middleware_base_url: str | None = None
    codestra_middleware_token_url: str | None = None
    codestra_middleware_client_id: str | None = None
    codestra_middleware_client_secret: str | None = None

    field_encryption_key: str | None = None
    provider_timeout_seconds: float = 30.0

    bank_provider: Literal["disabled", "plaid"] = "disabled"
    plaid_base_url: str = "https://sandbox.plaid.com"
    plaid_client_id: str | None = None
    plaid_secret: str | None = None
    plaid_client_name: str = "MoneyBeeLoans"
    plaid_products_csv: str = "transactions,auth"
    plaid_country_codes_csv: str = "US"
    plaid_webhook_url: str | None = None
    plaid_redirect_uri: str | None = None

    crm_provider: Literal["disabled", "generic_http"] = "disabled"
    crm_base_url: str | None = None
    crm_api_key: str | None = None
    crm_event_path: str = "/moneybee/events"

    kyb_provider: Literal["disabled", "generic_http"] = "disabled"
    kyb_base_url: str | None = None
    kyb_api_key: str | None = None
    kyb_verify_path: str = "/v1/business-verifications"

    credit_provider: Literal["disabled", "generic_http"] = "disabled"
    credit_base_url: str | None = None
    credit_api_key: str | None = None
    credit_request_path: str = "/v1/credit-requests"

    lender_provider: Literal["disabled", "generic_http"] = "disabled"
    lender_base_url: str | None = None
    lender_api_key: str | None = None
    lender_submission_path: str = "/v1/submissions"

    esign_provider: Literal["disabled", "docusign"] = "disabled"
    docusign_rest_base_url: str = "https://demo.docusign.net/restapi"
    docusign_account_id: str | None = None
    docusign_access_token: str | None = None
    docusign_template_id: str | None = None
    docusign_signer_role: str = "Borrower"

    email_provider: Literal["disabled", "sendgrid"] = "disabled"
    sendgrid_api_base_url: str = "https://api.sendgrid.com"
    sendgrid_api_key: str | None = None
    sendgrid_from_email: str | None = None
    sendgrid_from_name: str = "MoneyBeeLoans"

    sms_provider: Literal["disabled", "twilio"] = "disabled"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None

    object_storage_mode: Literal["disabled", "s3"] = "disabled"
    object_storage_endpoint: str | None = None
    object_storage_region: str | None = None
    object_storage_bucket: str | None = None
    object_storage_access_key: str | None = None
    object_storage_secret_key: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_csv.split(",") if item.strip()]

    @property
    def plaid_products(self) -> list[str]:
        return [
            item.strip()
            for item in self.plaid_products_csv.split(",")
            if item.strip()
        ]

    @property
    def plaid_country_codes(self) -> list[str]:
        return [
            item.strip()
            for item in self.plaid_country_codes_csv.split(",")
            if item.strip()
        ]

    @model_validator(mode="after")
    def secure_environment(self) -> "Settings":
        legacy = "auth.codestra.agency"
        if legacy in self.oidc_issuer or legacy in self.oidc_jwks_url:
            raise ValueError("Legacy identity host is forbidden")
        if self.app_env in {"staging", "production"}:
            if self.local_auth_bypass or self.auto_create_schema:
                raise ValueError("Local bypass/schema creation must be disabled")
            if not self.oidc_issuer.startswith("https://auth.codestra.co/"):
                raise ValueError("Canonical issuer must use auth.codestra.co")
            if self.bank_provider == "plaid" and not all(
                [
                    self.plaid_client_id,
                    self.plaid_secret,
                    self.field_encryption_key,
                ]
            ):
                raise ValueError(
                    "Plaid requires credentials and FIELD_ENCRYPTION_KEY"
                )
            if self.email_provider == "sendgrid" and not all(
                [self.sendgrid_api_key, self.sendgrid_from_email]
            ):
                raise ValueError("SendGrid configuration is incomplete")
            if self.sms_provider == "twilio" and not all(
                [
                    self.twilio_account_sid,
                    self.twilio_auth_token,
                    self.twilio_from_number,
                ]
            ):
                raise ValueError("Twilio configuration is incomplete")
            if self.object_storage_mode == "s3" and not all(
                [
                    self.object_storage_endpoint,
                    self.object_storage_region,
                    self.object_storage_bucket,
                    self.object_storage_access_key,
                    self.object_storage_secret_key,
                ]
            ):
                raise ValueError("S3 object storage configuration is incomplete")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
