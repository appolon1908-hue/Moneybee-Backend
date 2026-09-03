import hashlib
import hmac
import json
import re
import time

from app.config import settings
from app.integrations.base import MiddlewareResult, ProviderError
from app.integrations.http import provider_request


MIDDLEWARE_CONTRACT = "moneybee.event-envelope.v1"


def canonical_event_type(event_type: str) -> str:
    """Translate legacy internal names to the versioned integration vocabulary."""
    if "." in event_type:
        return event_type
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", event_type).lower()
    aliases = {
        "lead_submitted": "lead.created",
        "bank_webhook_received": "bank.provider_event_received",
        "plaid_webhook_received": "bank.provider_event_received",
    }
    return aliases.get(snake, snake) + ".v1"


def middleware_event_url(base_url: str, event_path: str) -> str:
    base = base_url.strip().rstrip("/")
    path = "/" + event_path.strip().lstrip("/")
    if not base.startswith("https://") and settings.app_env in {"staging", "production"}:
        raise ProviderError("codestra", "Middleware URL must use HTTPS")
    return base + path


def serialize_event_envelope(envelope: dict) -> bytes:
    """Return the exact canonical JSON bytes signed and transmitted to Codestra."""
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_outbound_event(raw_body: bytes, timestamp: str, secret: str) -> str:
    signed_payload = timestamp.encode("utf-8") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class CodestraProvider:
    name = "codestra"

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._expires_at = 0.0

    async def _token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        if not all(
            [
                settings.codestra_middleware_token_url,
                settings.codestra_middleware_client_id,
                settings.codestra_middleware_client_secret,
            ]
        ):
            raise ProviderError("codestra", "OAuth client configuration is incomplete")
        data = {"grant_type": "client_credentials"}
        if settings.codestra_middleware_scope:
            data["scope"] = settings.codestra_middleware_scope
        result = await provider_request(
            provider="codestra",
            method="POST",
            url=str(settings.codestra_middleware_token_url),
            data=data,
            auth=(
                str(settings.codestra_middleware_client_id),
                str(settings.codestra_middleware_client_secret),
            ),
            retries=1,
        )
        token = result.get("access_token") if isinstance(result, dict) else None
        if not token:
            raise ProviderError("codestra", "OAuth response did not contain access_token")
        self._access_token = str(token)
        self._expires_at = time.time() + int(result.get("expires_in", 300))
        return self._access_token

    async def access_token(self) -> str:
        """Return the cached service token for approved server-side SDK clients."""
        return await self._token()

    async def publish(
        self,
        *,
        event_id: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        aggregate_version: int | None,
        tenant_id: str | None,
        correlation_id: str | None,
        causation_id: str | None,
        occurred_at: str,
        payload: dict,
    ) -> MiddlewareResult:
        if not settings.codestra_middleware_base_url:
            raise ProviderError("codestra", "Middleware base URL is not configured")
        signing_secret = settings.codestra_middleware_webhook_secret
        if settings.app_env in {"staging", "production"} and not signing_secret:
            raise ProviderError("codestra", "Middleware signing secret is not configured")

        token = await self._token()
        canonical_type = canonical_event_type(event_type)
        envelope = {
            "contract": MIDDLEWARE_CONTRACT,
            "event_id": event_id,
            "event_type": canonical_type,
            "aggregate": {
                "type": aggregate_type,
                "id": aggregate_id,
                "version": aggregate_version,
            },
            "tenant_id": tenant_id,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "occurred_at": occurred_at,
            "payload": payload,
            "source": "moneybee",
            "schema_version": 1,
        }
        raw_body = serialize_event_envelope(envelope)
        timestamp = str(int(time.time()))
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": event_id,
            "X-MoneyBee-Event-ID": event_id,
            "X-MoneyBee-Timestamp": timestamp,
        }
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        if signing_secret:
            headers["X-MoneyBee-Signature"] = sign_outbound_event(
                raw_body,
                timestamp,
                signing_secret,
            )

        result = await provider_request(
            provider="codestra",
            method="POST",
            url=middleware_event_url(
                settings.codestra_middleware_base_url,
                settings.codestra_middleware_event_path,
            ),
            headers=headers,
            content=raw_body,
        )
        external_id = None
        status = "accepted"
        if isinstance(result, dict):
            external_id = result.get("event_id") or result.get("receipt_id") or result.get("id")
            status = str(result.get("status") or status)
        return MiddlewareResult(
            provider=self.name,
            external_id=str(external_id) if external_id else None,
            accepted=True,
            response={
                "status": status,
                "contract": MIDDLEWARE_CONTRACT,
                "event_type": canonical_type,
            },
        )
