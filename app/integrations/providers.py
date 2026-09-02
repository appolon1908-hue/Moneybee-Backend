from urllib.parse import quote

from app.config import settings
from app.integrations.base import ProviderError
from app.integrations.http import provider_request


def _bearer(token: str | None, provider: str) -> dict[str, str]:
    if not token:
        raise ProviderError(provider, "Provider credential is not configured")
    return {"Authorization": f"Bearer {token}"}


class GenericCRMAdapter:
    async def send_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload: dict,
    ) -> dict:
        if not settings.crm_base_url:
            raise ProviderError("crm", "CRM base URL is not configured")
        return await provider_request(
            provider="crm",
            method="POST",
            url=settings.crm_base_url.rstrip("/") + settings.crm_event_path,
            headers=_bearer(settings.crm_api_key, "crm"),
            json={
                "event_type": event_type,
                "aggregate_id": aggregate_id,
                "payload": payload,
            },
        )


class GenericKYBAdapter:
    async def verify_business(self, payload: dict) -> dict:
        if not settings.kyb_base_url:
            raise ProviderError("kyb", "KYB base URL is not configured")
        return await provider_request(
            provider="kyb",
            method="POST",
            url=settings.kyb_base_url.rstrip("/") + settings.kyb_verify_path,
            headers=_bearer(settings.kyb_api_key, "kyb"),
            json=payload,
        )


class GenericCreditAdapter:
    async def request_credit(self, payload: dict) -> dict:
        if not settings.credit_base_url:
            raise ProviderError("credit", "Credit base URL is not configured")
        return await provider_request(
            provider="credit",
            method="POST",
            url=(
                settings.credit_base_url.rstrip("/")
                + settings.credit_request_path
            ),
            headers=_bearer(settings.credit_api_key, "credit"),
            json=payload,
        )


class GenericLenderAdapter:
    async def submit(self, payload: dict) -> dict:
        if not settings.lender_base_url:
            raise ProviderError("lender", "Lender base URL is not configured")
        return await provider_request(
            provider="lender",
            method="POST",
            url=(
                settings.lender_base_url.rstrip("/")
                + settings.lender_submission_path
            ),
            headers=_bearer(settings.lender_api_key, "lender"),
            json=payload,
        )


class DocuSignAdapter:
    def _envelope_url(self, envelope_id: str = "") -> str:
        if not settings.docusign_account_id or not settings.docusign_access_token:
            raise ProviderError("docusign", "DocuSign configuration is incomplete")
        account_id = quote(str(settings.docusign_account_id), safe="")
        suffix = f"/{quote(envelope_id, safe='')}" if envelope_id else ""
        return settings.docusign_rest_base_url.rstrip("/") + f"/v2.1/accounts/{account_id}/envelopes{suffix}"

    async def send_envelope(
        self,
        *,
        contract_id: str,
        signer_email: str,
        signer_name: str,
    ) -> dict:
        required = (
            settings.docusign_account_id,
            settings.docusign_access_token,
            settings.docusign_template_id,
        )
        if not all(required):
            raise ProviderError("docusign", "DocuSign configuration is incomplete")
        url = self._envelope_url()
        return await provider_request(
            provider="docusign",
            method="POST",
            url=url,
            headers={
                **_bearer(settings.docusign_access_token, "docusign"),
                "Content-Type": "application/json",
            },
            json={
                # DocuSign uses transactionId to deduplicate create-envelope
                # retries. The contract UUID is stable across worker crashes
                # and lost responses, so an accepted request is reconciled
                # instead of producing a second legal envelope.
                "transactionId": contract_id,
                "templateId": settings.docusign_template_id,
                "templateRoles": [
                    {
                        "email": signer_email,
                        "name": signer_name,
                        "roleName": settings.docusign_signer_role,
                        "clientUserId": contract_id,
                    }
                ],
                "status": "sent",
            },
            retries=1,
        )

    async def void_envelope(self, *, envelope_id: str, reason: str) -> dict:
        return await provider_request(
            provider="docusign",
            method="PUT",
            url=self._envelope_url(envelope_id),
            headers={**_bearer(settings.docusign_access_token, "docusign"), "Content-Type": "application/json"},
            json={"status": "voided", "voidedReason": reason},
            # A void is consequential and may have succeeded when its response
            # is lost. Never repeat it at the transport layer; the domain
            # reconciliation path performs a provider status read-back.
            retries=0,
        )

    async def envelope_status(self, *, envelope_id: str) -> dict:
        """Read provider state after an ambiguous consequential operation."""
        return await provider_request(
            provider="docusign",
            method="GET",
            url=self._envelope_url(envelope_id),
            headers=_bearer(settings.docusign_access_token, "docusign"),
            retries=0,
        )


class SendGridAdapter:
    async def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> dict:
        if not settings.sendgrid_from_email:
            raise ProviderError("sendgrid", "Sender email is not configured")
        return await provider_request(
            provider="sendgrid",
            method="POST",
            url=settings.sendgrid_api_base_url.rstrip("/") + "/v3/mail/send",
            headers={
                **_bearer(settings.sendgrid_api_key, "sendgrid"),
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": recipient}]}],
                "from": {
                    "email": settings.sendgrid_from_email,
                    "name": settings.sendgrid_from_name,
                },
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            },
            retries=1,
        )


class TwilioSMSAdapter:
    async def send(self, *, recipient: str, body: str) -> dict:
        required = (
            settings.twilio_account_sid,
            settings.twilio_auth_token,
            settings.twilio_from_number,
        )
        if not all(required):
            raise ProviderError("twilio", "Twilio configuration is incomplete")
        account_sid = quote(str(settings.twilio_account_sid), safe="")
        return await provider_request(
            provider="twilio",
            method="POST",
            url=(
                "https://api.twilio.com/2010-04-01/Accounts/"
                f"{account_sid}/Messages.json"
            ),
            auth=(
                str(settings.twilio_account_sid),
                str(settings.twilio_auth_token),
            ),
            data={
                "To": recipient,
                "From": settings.twilio_from_number,
                "Body": body,
            },
            retries=1,
        )
