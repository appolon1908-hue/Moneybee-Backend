import hashlib
import hmac
import json
import time

from app.config import settings
from app.integrations.base import PayoutResult, ProviderError
from app.integrations.http import provider_request


class StripeAdapter:
    name = "stripe"

    def _auth(self) -> tuple[str, str]:
        if not settings.stripe_secret_key:
            raise ProviderError("stripe", "Stripe secret key is not configured")
        return (settings.stripe_secret_key, "")

    def _url(self, path: str) -> str:
        return settings.stripe_api_base_url.rstrip("/") + path

    async def send_payout(
        self,
        *,
        idempotency_key: str,
        amount: str,
        currency: str,
        destination: str,
        description: str,
    ) -> PayoutResult:
        """Transfers platform balance to a connected Stripe account
        (destination = a Stripe connected account id, "acct_..."). Stripe
        amounts are the smallest currency unit (cents for USD)."""
        minor_units = str(int(round(float(amount) * 100)))
        result = await provider_request(
            provider="stripe",
            method="POST",
            url=self._url("/v1/transfers"),
            auth=self._auth(),
            headers={"Idempotency-Key": idempotency_key},
            data={
                "amount": minor_units,
                "currency": currency.lower(),
                "destination": destination,
                "description": description,
            },
        )
        return PayoutResult(
            provider=self.name,
            payout_id=str(result["id"]),
            status="paid" if not result.get("reversed") else "reversed",
            raw=result,
        )

    async def get_payout_status(self, payout_id: str) -> PayoutResult:
        result = await provider_request(
            provider="stripe",
            method="GET",
            url=self._url(f"/v1/transfers/{payout_id}"),
            auth=self._auth(),
        )
        return PayoutResult(
            provider=self.name,
            payout_id=str(result["id"]),
            status="paid" if not result.get("reversed") else "reversed",
            raw=result,
        )

    def verify_webhook(
        self,
        body: bytes,
        signature_header: str | None,
        *,
        tolerance_seconds: int = 300,
    ) -> bool:
        if not signature_header or not settings.stripe_webhook_secret:
            return False
        parts: dict[str, list[str]] = {}
        for item in signature_header.split(","):
            key, _, value = item.partition("=")
            parts.setdefault(key.strip(), []).append(value.strip())
        timestamps = parts.get("t")
        signatures = parts.get("v1")
        if not timestamps or not signatures:
            return False
        try:
            timestamp = int(timestamps[0])
        except ValueError:
            return False
        if abs(int(time.time()) - timestamp) > tolerance_seconds:
            return False
        signed_payload = f"{timestamp}.".encode() + body
        expected = hmac.new(
            settings.stripe_webhook_secret.encode(), signed_payload, hashlib.sha256
        ).hexdigest()
        return any(hmac.compare_digest(expected, candidate) for candidate in signatures)


class PayPalAdapter:
    name = "paypal"

    def _url(self, path: str) -> str:
        return settings.paypal_api_base_url.rstrip("/") + path

    async def _access_token(self) -> str:
        if not settings.paypal_client_id or not settings.paypal_client_secret:
            raise ProviderError("paypal", "PayPal credentials are not configured")
        # Fetched fresh per call rather than cached - PayPal payout volume
        # here doesn't justify token-cache complexity; revisit if this
        # becomes a hot path.
        result = await provider_request(
            provider="paypal",
            method="POST",
            url=self._url("/v1/oauth2/token"),
            auth=(settings.paypal_client_id, settings.paypal_client_secret),
            data={"grant_type": "client_credentials"},
        )
        return str(result["access_token"])

    async def send_payout(
        self,
        *,
        idempotency_key: str,
        amount: str,
        currency: str,
        destination: str,
        description: str,
    ) -> PayoutResult:
        """Sends a single-item PayPal Payout (destination = the recipient's
        PayPal email address). PayPal's Payouts API is batch-shaped even
        for one recipient."""
        token = await self._access_token()
        result = await provider_request(
            provider="paypal",
            method="POST",
            url=self._url("/v1/payments/payouts"),
            headers={
                "Authorization": f"Bearer {token}",
                "PayPal-Request-Id": idempotency_key,
            },
            json={
                "sender_batch_header": {
                    "sender_batch_id": idempotency_key,
                    "email_subject": "You have a payout from MoneyBee",
                },
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "amount": {"value": amount, "currency": currency.upper()},
                        "note": description,
                        "receiver": destination,
                        "sender_item_id": idempotency_key,
                    }
                ],
            },
        )
        batch_header = result.get("batch_header", {})
        return PayoutResult(
            provider=self.name,
            payout_id=str(batch_header.get("payout_batch_id", "")),
            status=str(batch_header.get("batch_status", "unknown")).lower(),
            raw=result,
        )

    async def get_payout_status(self, payout_id: str) -> PayoutResult:
        token = await self._access_token()
        result = await provider_request(
            provider="paypal",
            method="GET",
            url=self._url(f"/v1/payments/payouts/{payout_id}"),
            headers={"Authorization": f"Bearer {token}"},
        )
        batch_header = result.get("batch_header", {})
        return PayoutResult(
            provider=self.name,
            payout_id=str(batch_header.get("payout_batch_id", payout_id)),
            status=str(batch_header.get("batch_status", "unknown")).lower(),
            raw=result,
        )

    async def verify_webhook(self, body: bytes, headers: dict[str, str]) -> bool:
        """PayPal's webhook signature is an RSA signature over a cert chain
        it hosts, not a shared-secret HMAC - rather than reimplement that
        verification locally, ask PayPal's own verify-webhook-signature API
        to check it, matching the transmission headers against the
        configured webhook_id."""
        if not settings.paypal_webhook_id:
            return False
        try:
            event = json.loads(body)
        except ValueError:
            return False
        token = await self._access_token()
        result = await provider_request(
            provider="paypal",
            method="POST",
            url=self._url("/v1/notifications/verify-webhook-signature"),
            headers={"Authorization": f"Bearer {token}"},
            json={
                "transmission_id": headers.get("paypal-transmission-id"),
                "transmission_time": headers.get("paypal-transmission-time"),
                "transmission_sig": headers.get("paypal-transmission-sig"),
                "cert_url": headers.get("paypal-cert-url"),
                "auth_algo": headers.get("paypal-auth-algo"),
                "webhook_id": settings.paypal_webhook_id,
                "webhook_event": event,
            },
        )
        return str(result.get("verification_status", "")).upper() == "SUCCESS"
