import time

from app.config import settings
from app.event_contracts import build_event_envelope, canonical_event_type
from app.integrations.base import MiddlewareResult, ProviderError
from app.integrations.http import provider_request


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
        idempotency_key: str,
        schema_version: int = 1,
        delivery_attempt: int | None = None,
    ) -> MiddlewareResult:
        if not settings.codestra_middleware_base_url:
            raise ProviderError("codestra", "Middleware base URL is not configured")
        token = await self._token()
        try:
            envelope = build_event_envelope(
                event_id=event_id,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_version=aggregate_version,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                occurred_at=occurred_at,
                payload=payload,
                idempotency_key=idempotency_key,
                schema_version=schema_version,
                delivery_attempt=delivery_attempt,
            )
        except ValueError as exc:
            raise ProviderError("codestra", f"Event contract is invalid: {exc}") from exc
        result = await provider_request(
            provider="codestra",
            method="POST",
            url=(
                settings.codestra_middleware_base_url.rstrip("/")
                + settings.codestra_middleware_event_path
            ),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
                "X-Correlation-Id": envelope["correlation_id"],
                "X-Codestra-Event-Id": envelope["id"],
                "X-Codestra-Event-Type": envelope["type"],
                "X-Codestra-Source": "moneybee-backend",
                "X-Codestra-Tenant-Id": envelope["tenant_id"],
            },
            json=envelope,
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
            response={"status": status},
        )


__all__ = ["CodestraProvider", "canonical_event_type"]
