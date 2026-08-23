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


@dataclass(frozen=True)
class ProviderHealth:
    provider_type: str
    provider: str
    selected: bool
    configured: bool


class BankAdapter(Protocol):
    name: str

    async def create_link_session(self, application_id: str) -> dict:\n        ...

    async def exchange_public_token(self, public_token: str) -> dict:\n        ...

    async def get_accounts(self, access_token: str) -> dict:\n        ...

    async def sync_transactions(
        self,
        access_token: str,
        cursor: str | None,
    ) -> dict: ...

    async def remove_item(self, access_token: str) -> None:\n        ...


class CRMAdapter(Protocol):
    async def send_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload: dict,
    ) -> dict: ...


class KYBAdapter(Protocol):
    async def verify_business(self, payload: dict) -> dict:\n        ...


class CreditAdapter(Protocol):
    async def request_credit(self, payload: dict) -> dict:\n        ...


class LenderAdapter(Protocol):
    async def submit(self, payload: dict) -> dict:\n        ...


class ESignAdapter(Protocol):
    async def send_envelope(
        self,
        *,
        contract_id: str,
        signer_email: str,
        signer_name: str,
    ) -> dict: ...


class EmailAdapter(Protocol):
    async def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> dict: ...


class SMSAdapter(Protocol):
    async def send(self, *, recipient: str, body: str) -> dict:\n        ...


class ObjectStorageAdapter(Protocol):
    async def put_private(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> dict: ...

    async def presigned_download(
        self,
        *,
        object_key: str,
        expires_seconds: int,
    ) -> str: ...
