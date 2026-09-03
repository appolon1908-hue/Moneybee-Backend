from dataclasses import dataclass
from typing import Protocol


class ProviderError(RuntimeError):
    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: int | None = None,
    ):
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"{provider}: {message}")


class UnknownOutcomeError(ProviderError):
    """A consequential provider request may have succeeded remotely.

    Callers must reconcile using provider read-back before attempting the
    mutation again.  Keeping this distinct from an ordinary outage prevents
    workers from blindly duplicating money movement or legal/provider actions.
    """


@dataclass(frozen=True)
class ProviderHealth:
    provider_type: str
    provider: str
    selected: bool
    configured: bool


@dataclass(frozen=True)
class MiddlewareResult:
    provider: str
    external_id: str | None
    accepted: bool
    response: dict


class MiddlewareProvider(Protocol):
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
        ...


class BankAdapter(Protocol):
    name: str

    async def create_link_session(self, application_id: str) -> dict:
        ...

    async def exchange_public_token(self, public_token: str) -> dict:
        ...

    async def resolve_access_token(self, credential_reference: str) -> str:
        ...

    async def get_accounts(self, access_token: str) -> dict:
        ...

    async def sync_transactions(
        self,
        access_token: str,
        cursor: str | None,
    ) -> dict:
        ...

    async def remove_item(self, access_token: str) -> None:
        ...


class CRMAdapter(Protocol):
    async def send_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload: dict,
    ) -> dict:
        ...


class KYBAdapter(Protocol):
    async def verify_business(self, payload: dict) -> dict:
        ...


class CreditAdapter(Protocol):
    async def request_credit(self, payload: dict) -> dict:
        ...


class LenderAdapter(Protocol):
    async def submit(self, payload: dict) -> dict:
        ...


class ESignAdapter(Protocol):
    async def send_envelope(
        self,
        *,
        contract_id: str,
        signer_email: str,
        signer_name: str,
    ) -> dict:
        ...

    async def void_envelope(self, *, envelope_id: str, reason: str) -> dict:
        ...

    async def envelope_status(self, *, envelope_id: str) -> dict:
        ...


class EmailAdapter(Protocol):
    async def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> dict:
        ...


class SMSAdapter(Protocol):
    async def send(self, *, recipient: str, body: str) -> dict:
        ...


@dataclass(frozen=True)
class PayoutResult:
    provider: str
    payout_id: str
    status: str
    raw: dict


class PaymentAdapter(Protocol):
    name: str

    async def send_payout(
        self,
        *,
        idempotency_key: str,
        amount: str,
        currency: str,
        destination: str,
        description: str,
    ) -> PayoutResult:
        ...

    async def get_payout_status(self, payout_id: str) -> PayoutResult:
        ...


class ObjectStorageAdapter(Protocol):
    async def put_private(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> dict:
        ...

    async def get_private(self, *, object_key: str, version_id: str | None = None) -> bytes:
        ...

    async def delete_private(self, *, object_key: str) -> None:
        ...

    async def presigned_download(
        self,
        *,
        object_key: str,
        expires_seconds: int,
        version_id: str | None = None,
    ) -> str:
        ...


@dataclass(frozen=True)
class MalwareScanResult:
    provider: str
    clean: bool
    signature: str | None
    raw: str


class MalwareScanner(Protocol):
    name: str

    async def scan(self, content: bytes) -> MalwareScanResult:
        ...
