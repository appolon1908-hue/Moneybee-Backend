"""MoneyBee-specific wrapper around the immutable Codestra connector SDK."""

from __future__ import annotations

from typing import Any

from codestra_moneybee_connectors import (
    AdapterRequestContext,
    AuthenticationError,
    AuthorizationError,
    CapabilityDisabledError,
    CodestraMiddlewareClient,
    DependencyUnavailableError,
    IdempotencyConflictError,
    MiddlewareClientConfig,
    Operation,
    ProviderRejectedError,
    ProviderTimeoutError,
    RateLimitError,
    TenantAccessError,
    UnknownOutcomeError,
    ValidationError,
)

from app.config import settings
from app.integrations.base import ProviderError
from app.integrations.middleware import CodestraProvider


_KNOWN_CONNECTOR_ERRORS = (
    AuthenticationError,
    AuthorizationError,
    DependencyUnavailableError,
    IdempotencyConflictError,
    ProviderRejectedError,
    ProviderTimeoutError,
    RateLimitError,
    TenantAccessError,
    ValidationError,
)
_READ_ERRORS = (UnknownOutcomeError, *_KNOWN_CONNECTOR_ERRORS)


class MoneyBeeCodestraCommands:
    """Governed command-plane integration; disabled until explicitly activated.

    A mutation is attempted once. An ambiguous transport result is returned as a
    reconciliation-required provider error and must be read back by operation ID
    before any retry.
    """

    def __init__(self, legacy_auth: CodestraProvider | None = None) -> None:
        self._auth = legacy_auth or CodestraProvider()

    def _client(self) -> CodestraMiddlewareClient:
        if not settings.codestra_middleware_base_url:
            raise ProviderError("codestra", "Middleware base URL is not configured")
        return CodestraMiddlewareClient(
            MiddlewareClientConfig(
                base_url=settings.codestra_middleware_base_url,
                enabled=settings.codestra_sdk_enabled,
                timeout_seconds=settings.provider_timeout_seconds,
                allowed_capabilities=settings.codestra_sdk_capabilities,
            ),
            self._auth.access_token,
        )

    @staticmethod
    def context(
        *,
        tenant_id: str,
        principal: str,
        request_id: str,
        correlation_id: str,
        operation_id: str,
        idempotency_key: str,
        provider: str = "codestra",
        provider_operation_id: str | None = None,
    ) -> AdapterRequestContext:
        release_id = settings.source_sha
        if not release_id:
            raise ProviderError("codestra", "SOURCE_SHA is required for SDK operations")
        return AdapterRequestContext(
            tenant_id=tenant_id,
            principal=principal,
            request_id=request_id,
            correlation_id=correlation_id,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            provider=provider,
            release_id=release_id,
            provider_operation_id=provider_operation_id,
        )

    @staticmethod
    def _known_error(exc: Exception) -> ProviderError:
        code = getattr(exc, "code", "CONNECTOR_ERROR")
        return ProviderError("codestra", f"{code}: {exc}")

    async def submit_crm_projection(
        self,
        context: AdapterRequestContext,
        payload: dict[str, Any],
    ) -> Operation:
        client = self._client()
        try:
            return await client.submit_command(
                context,
                command_type="crm.project",
                target="odoo",
                capability="ODOO_WRITE",
                payload=payload,
            )
        except CapabilityDisabledError as exc:
            raise ProviderError(
                "codestra",
                "Codestra SDK command capability is disabled",
            ) from exc
        except UnknownOutcomeError as exc:
            raise ProviderError(
                "codestra",
                "Command outcome is unknown; reconcile by operation ID before retry",
            ) from exc
        except _KNOWN_CONNECTOR_ERRORS as exc:
            raise self._known_error(exc) from exc
        finally:
            await client.aclose()

    async def read_operation(self, context: AdapterRequestContext) -> Operation:
        client = self._client()
        try:
            return await client.get_operation(context)
        except CapabilityDisabledError as exc:
            raise ProviderError("codestra", "Codestra SDK is disabled") from exc
        except _READ_ERRORS as exc:
            raise self._known_error(exc) from exc
        finally:
            await client.aclose()
