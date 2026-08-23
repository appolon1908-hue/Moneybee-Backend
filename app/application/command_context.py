from dataclasses import dataclass
from uuid import UUID

from fastapi import Request


@dataclass(frozen=True)
class CommandContext:
    request_id: str
    correlation_id: str
    actor_id: UUID | None = None
    tenant_id: UUID | None = None
    legal_entity_id: UUID | None = None
    idempotency_key: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> "CommandContext":
        request_id = getattr(request.state, "request_id", request.headers.get("X-Request-ID", ""))
        correlation_id = getattr(
            request.state,
            "correlation_id",
            request.headers.get("X-Correlation-ID", request_id),
        )
        return cls(
            request_id=request_id,
            correlation_id=correlation_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        )
