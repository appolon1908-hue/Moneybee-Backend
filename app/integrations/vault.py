import uuid

from app.config import settings
from app.integrations.base import ProviderError
from app.integrations.http import provider_request


class VaultCredentialStore:
    """Self-hosted HashiCorp Vault, KV v2 secrets engine, as the external
    store for bank access tokens - see app/banking.py for why nothing
    calling this ever persists the raw token itself.

    Chosen over a managed-cloud secrets service (AWS Secrets Manager, GCP
    Secret Manager) because this project deploys to a single self-hosted
    Docker Compose host (see deploy/), not any particular cloud vendor -
    Vault is the one credential store that fits that target without
    introducing a cloud dependency the rest of the stack doesn't have.
    """

    name = "vault"

    def _headers(self) -> dict[str, str]:
        if not settings.vault_token:
            raise ProviderError("vault", "Vault is not configured")
        return {"X-Vault-Token": settings.vault_token}

    def _data_url(self, path: str) -> str:
        if not settings.vault_addr:
            raise ProviderError("vault", "Vault is not configured")
        mount = settings.vault_mount.strip("/")
        return f"{settings.vault_addr.rstrip('/')}/v1/{mount}/data/{path}"

    async def store(self, secret: str) -> str:
        reference = f"{settings.vault_path_prefix.strip('/')}/{uuid.uuid4()}"
        await provider_request(
            provider="vault",
            method="POST",
            url=self._data_url(reference),
            headers=self._headers(),
            json={"data": {"value": secret}},
            retries=1,
        )
        return reference

    async def resolve(self, reference: str) -> str:
        result = await provider_request(
            provider="vault",
            method="GET",
            url=self._data_url(reference),
            headers=self._headers(),
            retries=1,
        )
        try:
            return str(result["data"]["data"]["value"])
        except (KeyError, TypeError) as exc:
            raise ProviderError("vault", "Credential reference not found") from exc
