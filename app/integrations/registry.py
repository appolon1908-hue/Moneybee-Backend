from app.config import settings
from app.integrations.base import ProviderError, ProviderHealth
from app.integrations.experian import ExperianCommercialAdapter
from app.integrations.middleware import CodestraProvider
from app.integrations.middesk import MiddeskAdapter
from app.integrations.odoo import OdooCommunityAdapter
from app.integrations.plaid import PlaidAdapter
from app.integrations.providers import (
    DocuSignAdapter,
    GenericCRMAdapter,
    GenericCreditAdapter,
    GenericKYBAdapter,
    GenericLenderAdapter,
    SendGridAdapter,
    TwilioSMSAdapter,
)
from app.integrations.storage import S3ObjectStorageAdapter


def bank_adapter() -> PlaidAdapter:
    if settings.bank_provider == "plaid":
        return PlaidAdapter()
    raise ProviderError("bank", "Bank provider is disabled")


def middleware_adapter() -> CodestraProvider:
    if settings.middleware_provider == "codestra":
        return CodestraProvider()
    raise ProviderError("middleware", "Middleware provider is disabled")


def crm_adapter() -> GenericCRMAdapter | OdooCommunityAdapter:
    if settings.crm_provider == "generic_http":
        return GenericCRMAdapter()
    if settings.crm_provider == "odoo":
        return OdooCommunityAdapter()
    raise ProviderError("crm", "CRM provider is disabled")


def kyb_adapter() -> GenericKYBAdapter | MiddeskAdapter:
    if settings.kyb_provider == "generic_http":
        return GenericKYBAdapter()
    if settings.kyb_provider == "middesk":
        return MiddeskAdapter()
    raise ProviderError("kyb", "KYB provider is disabled")


def credit_adapter() -> GenericCreditAdapter | ExperianCommercialAdapter:
    if settings.credit_provider == "generic_http":
        return GenericCreditAdapter()
    if settings.credit_provider == "experian":
        return ExperianCommercialAdapter()
    raise ProviderError("credit", "Credit provider is disabled")


def lender_adapter() -> GenericLenderAdapter:
    if settings.lender_provider == "generic_http":
        return GenericLenderAdapter()
    raise ProviderError("lender", "Lender provider is disabled")


def esign_adapter() -> DocuSignAdapter:
    if settings.esign_provider == "docusign":
        return DocuSignAdapter()
    raise ProviderError("esign", "E-sign provider is disabled")


def email_adapter() -> SendGridAdapter:
    if settings.email_provider == "sendgrid":
        return SendGridAdapter()
    raise ProviderError("email", "Email provider is disabled")


def sms_adapter() -> TwilioSMSAdapter:
    if settings.sms_provider == "twilio":
        return TwilioSMSAdapter()
    raise ProviderError("sms", "SMS provider is disabled")


def storage_adapter() -> S3ObjectStorageAdapter:
    if settings.object_storage_mode == "s3":
        return S3ObjectStorageAdapter()
    raise ProviderError("storage", "Object storage is disabled")


def provider_statuses() -> list[ProviderHealth]:
    return [
        ProviderHealth(
            "middleware",
            settings.middleware_provider,
            settings.middleware_provider != "disabled",
            bool(
                settings.codestra_middleware_base_url
                and settings.codestra_middleware_token_url
                and settings.codestra_middleware_client_id
                and settings.codestra_middleware_client_secret
            ),
        ),
        ProviderHealth(
            "bank",
            settings.bank_provider,
            settings.bank_provider != "disabled",
            bool(
                settings.plaid_client_id
                and settings.plaid_secret
                and settings.field_encryption_key
            ),
        ),
        ProviderHealth(
            "crm",
            settings.crm_provider,
            settings.crm_provider != "disabled",
            bool(
                (
                    settings.crm_provider == "generic_http"
                    and settings.crm_base_url
                    and settings.crm_api_key
                )
                or (
                    settings.crm_provider == "odoo"
                    and settings.odoo_base_url
                    and settings.odoo_database
                    and settings.odoo_api_key
                )
            ),
        ),
        ProviderHealth(
            "kyb",
            settings.kyb_provider,
            settings.kyb_provider != "disabled",
            bool(
                (
                    settings.kyb_provider == "generic_http"
                    and settings.kyb_base_url
                    and settings.kyb_api_key
                )
                or (
                    settings.kyb_provider == "middesk"
                    and settings.middesk_api_key
                )
            ),
        ),
        ProviderHealth(
            "credit",
            settings.credit_provider,
            settings.credit_provider != "disabled",
            bool(
                (
                    settings.credit_provider == "generic_http"
                    and settings.credit_base_url
                    and settings.credit_api_key
                )
                or (
                    settings.credit_provider == "experian"
                    and settings.experian_base_url
                    and settings.experian_token_url
                    and settings.experian_client_id
                    and settings.experian_client_secret
                    and settings.experian_business_search_path
                    and settings.experian_business_report_path_template
                    and settings.experian_search_mapping_json != "{}"
                )
            ),
        ),
        ProviderHealth(
            "lender",
            settings.lender_provider,
            settings.lender_provider != "disabled",
            bool(settings.lender_base_url and settings.lender_api_key),
        ),
        ProviderHealth(
            "esign",
            settings.esign_provider,
            settings.esign_provider != "disabled",
            bool(
                settings.docusign_account_id
                and settings.docusign_access_token
                and settings.docusign_template_id
            ),
        ),
        ProviderHealth(
            "email",
            settings.email_provider,
            settings.email_provider != "disabled",
            bool(settings.sendgrid_api_key and settings.sendgrid_from_email),
        ),
        ProviderHealth(
            "sms",
            settings.sms_provider,
            settings.sms_provider != "disabled",
            bool(
                settings.twilio_account_sid
                and settings.twilio_auth_token
                and settings.twilio_from_number
            ),
        ),
        ProviderHealth(
            "storage",
            settings.object_storage_mode,
            settings.object_storage_mode != "disabled",
            bool(
                settings.object_storage_endpoint
                and settings.object_storage_region
                and settings.object_storage_bucket
                and settings.object_storage_access_key
                and settings.object_storage_secret_key
            ),
        ),
    ]
