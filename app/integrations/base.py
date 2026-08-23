from dataclasses import dataclass
from typing import Protocol, Mapping, Any

@dataclass(frozen=True)
class ProviderResult:
    provider: str
    success: bool
    external_id: str | None = None
    retryable: bool = False
    error_code: str | None = None
    retry_after_seconds: int | None = None

class IntegrationAdapter(Protocol):
    name: str
    async def execute(self, operation: str, payload: Mapping[str, Any], *, idempotency_key: str | None = None) -> ProviderResult: ...
