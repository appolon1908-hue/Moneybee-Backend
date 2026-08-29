from functools import lru_cache
import json
from typing import Literal
import warnings

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "dev", "staging", "production"] = "local"
    database_url: str = "sqlite+aiosqlite:///./moneybee.db"
    redis_url: str = "redis://localhost:6379/0"
    auto_create_schema: bool = False
    local_auth_bypass: bool = False
    local_identity_enforcement: bool = True
    cors_origins_csv: str = (
        "http://localhost:5173,http://localhost:5174,"
        "http://localhost:5175,http://localhost:5176"
    )
    oidc_issuer: str = "https://auth.codestra.co/realms/codestra"
    oidc_audience: str = "moneybee-api"
    oidc_jwks_url: str = (
        "https://auth.codestra.co/realms/codestra/protocol/openid-connect/certs"
    )
    oidc_algorithms_csv: str = "RS256"
    borrower_oidc_client_ids_csv: str = "moneybee-borrower"
    lender_oidc_client_ids_csv: str = "moneybee-lender"
    admin_oidc_client_ids_csv: str = "moneybee-admin"

    # To send SMS: POST {codestra_middleware_base_url}/commands/sms
    # Do not use Twilio directly; all SMS routes through Middleware -> Telnexa.
    codestra_middleware_base_url: str | None = None
    codestra_middleware_token_url: str | None = None
    codestra_middleware_client_id: str | None = None
    codestra_middleware_client_secret: str | None = None
    middleware_provider: Literal["disabled", "codestra"] = "disabled"
    codestra_middleware_event_path: str = "/v1/events"
    codestra_middleware_scope: str | None = None
    codestra_middleware_webhook_secret: str | None = None
    codestra_middleware_webhook_tolerance_seconds: int = 60
    provider_webhook_allowlist_csv: str = (
        "lender,docusign,sendgrid,odoo,n8n,experian"
    )
    provider_webhook_secrets_json: str = "{}"
    provider_webhook_tolerance_seconds: int = 60
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    public_rate_limit_per_minute: int = 120
    webhook_rate_limit_per_minute: int = 240

    field_encryption_key: str | None = None
    provider_timeout_seconds: float = 30.0

    source_sha: str | None = None
    api_image_digest: str | None = None
    frontend_image_digest: str | None = None
    migration_head: str | None = None
    configuration_checksum: str | None = None
    sbom_digest: str | None = None
    provenance_digest: str | None = None
    backup_reference: str | None = None
    backup_status: Literal["NOT_CONFIGURED", "PASS", "FAIL"] = "NOT_CONFIGURED"
    restore_status: Literal["NOT_CONFIGURED", "PASS", "FAIL"] = "NOT_CONFIGURED"
    staging_status: Literal["NOT_CONFIGURED", "PASS", "FAIL"] = "NOT_CONFIGURED"

    bank_provider: Literal["disabled", "plaid"] = "disabled"
    plaid_base_url: str = "https://sandbox.plaid.com"
    plaid_client_id: str | None = None
    plaid_secret: str | None = None
    plaid_client_name: str = "MoneyBeeLoans"
    plaid_products_csv: str = "transactions,auth"
    plaid_country_codes_csv: str = "US"
    plaid_webhook_url: str | None = None
    plaid_redirect_uri: str | None = None

    crm_provider: Literal["disabled", "generic_http", "odoo"] = "disabled"
    crm_base_url: str | None = None
    crm_api_key: str | None = None
    crm_event_path: str = "/moneybee/events"

    odoo_base_url: str | None = None
    odoo_database: str | None = None
    odoo_api_mode: Literal["auto", "json2", "xmlrpc"] = "auto"
    odoo_username: str | None = None
    odoo_api_key: str | None = None

    kyb_provider: Literal["disabled", "generic_http", "middesk"] = "disabled"
    kyb_base_url: str | None = None
    kyb_api_key: str | None = None
    kyb_verify_path: str = "/v1/business-verifications"

    middesk_base_url: str = "https://api-sandbox.middesk.com"
    middesk_api_key: str | None = None
    middesk_webhook_secret: str | None = None

    credit_provider: Literal["disabled", "generic_http", "experian"] = "disabled"
    credit_base_url: str | None = None
    credit_api_key: str | None = None
    credit_request_path: str = "/v1/credit-requests"

    # TODO(security): Experian is called directly from Moneybee.
    # Credit bureau calls must be routed through Codestra Middleware for
    # audit logging, idempotency, and write authority enforcement.
    # Track: https://github.com/appolon1908-hue/Middleware-/issues
    # Until then, ensure EXPERIAN_* vars are never committed and
    # are injected only via secrets management.
    experian_base_url: str | None = None
    experian_token_url: str | None = None
    experian_client_id: str | None = None
    experian_client_secret: str | None = None
    experian_scope: str | None = None
    experian_token_auth_style: Literal["basic", "body"] = "basic"
    experian_business_search_path: str | None = None
    experian_business_report_path_template: str | None = None
    experian_search_mapping_json: str = "{}"
    experian_search_id_path: str = "id"
    experian_score_path: str = ""
    experian_risk_class_path: str = ""
    experian_bankruptcy_count_path: str = ""
    experian_lien_count_path: str = ""
    experian_judgment_count_path: str = ""

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

    sms_provider: Literal["disabled"] = "disabled"

    object_storage_mode: Literal["disabled", "s3"] = "disabled"
    object_storage_endpoint: str | None = None
    object_storage_region: str | None = None
    object_storage_bucket: str | None = None
    object_storage_access_key: str | None = None
    object_storage_secret_key: str | None = None

    def __getattr__(self, name: str) -> None:
        if name.startswith("twilio_"):
            return None
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    @staticmethod
    def _csv_set(value: str) -> frozenset[str]:
        return frozenset(item.strip() for item in value.split(",") if item.strip())

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_csv.split(",") if item.strip()]

    @property
    def portal_client_ids(self) -> dict[str, frozenset[str]]:
        return {
            "borrower": self._csv_set(self.borrower_oidc_client_ids_csv),
            "lender": self._csv_set(self.lender_oidc_client_ids_csv),
            "admin": self._csv_set(self.admin_oidc_client_ids_csv),
        }

    @property
    def provider_webhook_allowlist(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.provider_webhook_allowlist_csv.split(",")
            if item.strip()
        }

    @property
    def provider_webhook_secrets(self) -> dict[str, str]:
        try:
            value = json.loads(self.provider_webhook_secrets_json)
        except json.JSONDecodeError as exc:
            raise ValueError("PROVIDER_WEBHOOK_SECRETS_JSON must be valid JSON") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(secret, str)
            for key, secret in value.items()
        ):
            raise ValueError("PROVIDER_WEBHOOK_SECRETS_JSON must be a string map")
        return {key.lower(): secret for key, secret in value.items() if secret}

    @property
    def oidc_algorithms(self) -> list[str]:
        return [
            item.strip()
            for item in self.oidc_algorithms_csv.split(",")
            if item.strip()
        ]

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

        if (
            self.middleware_provider == "disabled"
            and self.app_env not in ("local", "test")
        ):
            warnings.warn(
                f"MIDDLEWARE_PROVIDER=disabled in app_env={self.app_env!r}. "
                "Call results, SMS events, and CRM sync will be silently dropped. "
                "Set MIDDLEWARE_PROVIDER=codestra to enable Middleware integration.",
                RuntimeWarning,
                stacklevel=2,
            )

        portal_clients = self.portal_client_ids
        if any(not values for values in portal_clients.values()):
            raise ValueError("Every MoneyBee portal requires at least one OIDC client ID")
        pairs = (("borrower", "lender"), ("borrower", "admin"), ("lender", "admin"))
        for left, right in pairs:
            if portal_clients[left] & portal_clients[right]:
                raise ValueError(
                    "Borrower, lender, and admin OIDC client IDs must be disjoint"
                )

        if self.app_env in {"staging", "production"}:
            if self.local_auth_bypass or self.auto_create_schema:
                raise ValueError("Local bypass/schema creation must be disabled")
            if not self.local_identity_enforcement:
                raise ValueError("Local identity enforcement must be enabled")
            if not self.oidc_issuer.startswith("https://auth.codestra.co/"):
                raise ValueError("Canonical issuer must use auth.codestra.co")
            if self.oidc_algorithms != ["RS256"]:
                raise ValueError("Production OIDC tokens must use RS256")
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
            if self.middleware_provider == "codestra" and not all(
                [
                    self.codestra_middleware_base_url,
                    self.codestra_middleware_token_url,
                    self.codestra_middleware_client_id,
                    self.codestra_middleware_client_secret,
                ]
            ):
                raise ValueError("Codestra middleware configuration is incomplete")
            if self.crm_provider == "odoo" and not all(
                [self.odoo_base_url, self.odoo_database, self.odoo_api_key]
            ):
                raise ValueError("Odoo configuration is incomplete")
            if self.kyb_provider == "middesk" and not self.middesk_api_key:
                raise ValueError("Middesk configuration is incomplete")
            if self.credit_provider == "experian" and not all(
                [
                    self.experian_base_url,
                    self.experian_token_url,
                    self.experian_client_id,
                    self.experian_client_secret,
                    self.experian_business_search_path,
                    self.experian_business_report_path_template,
                    self.experian_search_mapping_json != "{}",
                ]
            ):
                raise ValueError("Experian configuration is incomplete")
            if self.email_provider == "sendgrid" and not all(
                [self.sendgrid_api_key, self.sendgrid_from_email]
            ):
                raise ValueError("SendGrid configuration is incomplete")
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
