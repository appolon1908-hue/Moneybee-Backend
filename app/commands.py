from dataclasses import dataclass
import uuid

from fastapi import HTTPException, Request

from app.auth import Principal


@dataclass(frozen=True)
class CommandContext:
    principal: Principal
    request_id: str
    correlation_id: str
    idempotency_key: str | None
    tenant_id: str | None
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True)
class AcceptOfferCommand:
    offer_id: uuid.UUID
    expected_application_version: int | None


def parse_expected_version(value: str | None) -> int | None:
    if value is None:
        return None
    candidate = value.strip().removeprefix("W/").strip('"')
    try:
        version = int(candidate)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_EXPECTED_VERSION",
                "message": "If-Match must contain an integer aggregate version.",
            },
        ) from exc
    if version < 1:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_EXPECTED_VERSION",
                "message": "Expected version must be positive.",
            },
        )
    return version


def command_context(
    request: Request,
    principal: Principal,
    *,
    idempotency_key: str | None,
) -> CommandContext:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    correlation_id = request.headers.get("X-Correlation-ID") or request_id
    return CommandContext(
        principal=principal,
        request_id=request_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        tenant_id=principal.organization_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )

