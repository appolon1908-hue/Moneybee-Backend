import asyncio
import xmlrpc.client

from app.config import settings
from app.integrations.base import ProviderError
from app.integrations.http import provider_request


class OdooCommunityAdapter:
    """MoneyBee-to-Odoo projection adapter. MoneyBee remains authoritative."""

    name = "odoo"

    def _base_url(self) -> str:
        if not settings.odoo_base_url:
            raise ProviderError("odoo", "ODOO_BASE_URL is not configured")
        return settings.odoo_base_url.rstrip("/")

    def _database(self) -> str:
        if not settings.odoo_database:
            raise ProviderError("odoo", "ODOO_DATABASE is not configured")
        return settings.odoo_database

    def _api_key(self) -> str:
        if not settings.odoo_api_key:
            raise ProviderError("odoo", "ODOO_API_KEY is not configured")
        return settings.odoo_api_key

    async def server_version(self) -> dict:
        result = await provider_request(
            provider="odoo",
            method="GET",
            url=self._base_url() + "/web/version",
            retries=1,
        )
        if not isinstance(result, dict):
            raise ProviderError("odoo", "Version response was invalid")
        return result

    async def mode(self) -> str:
        if settings.odoo_api_mode != "auto":
            return settings.odoo_api_mode
        result = await self.server_version()
        info = result.get("version_info") or []
        version = info[0] if info else str(result.get("version") or "0").split(".")[0]
        return "json2" if int(version) >= 19 else "xmlrpc"

    async def json2_call(self, model: str, method: str, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json; charset=utf-8",
        }
        if settings.odoo_database:
            headers["X-Odoo-Database"] = settings.odoo_database
        result = await provider_request(
            provider="odoo",
            method="POST",
            url=f"{self._base_url()}/json/2/{model}/{method}",
            headers=headers,
            json=payload,
            retries=1,
        )
        return result if isinstance(result, dict) else {"result": result}

    def _xmlrpc_execute(self, model: str, method: str, args: list, kwargs: dict) -> dict:
        if not settings.odoo_username:
            raise ProviderError("odoo", "ODOO_USERNAME is required for XML-RPC")
        common = xmlrpc.client.ServerProxy(
            self._base_url() + "/xmlrpc/2/common",
            allow_none=True,
        )
        uid = common.authenticate(
            self._database(),
            settings.odoo_username,
            self._api_key(),
            {},
        )
        if not uid:
            raise ProviderError("odoo", "Authentication failed")
        objects = xmlrpc.client.ServerProxy(
            self._base_url() + "/xmlrpc/2/object",
            allow_none=True,
        )
        result = objects.execute_kw(
            self._database(),
            uid,
            self._api_key(),
            model,
            method,
            args,
            kwargs,
        )
        return result if isinstance(result, dict) else {"result": result}

    async def xmlrpc_call(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._xmlrpc_execute,
            model,
            method,
            args,
            kwargs or {},
        )

    async def send_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload: dict,
    ) -> dict:
        projection = dict(payload)
        projection.setdefault("event_type", event_type)
        projection.setdefault("aggregate_id", aggregate_id)
        projection.setdefault(
            "moneybee_lead_id",
            payload.get("lead_id") or aggregate_id,
        )
        projection.setdefault(
            "moneybee_application_id",
            payload.get("application_id"),
        )
        if await self.mode() == "json2":
            return await self.json2_call(
                "crm.lead",
                "moneybee_upsert",
                {"payload": projection},
            )
        return await self.xmlrpc_call(
            "crm.lead",
            "moneybee_upsert",
            [projection],
        )

    async def health(self) -> dict:
        selected_mode = await self.mode()
        if selected_mode == "json2":
            bridge = await self.json2_call("crm.lead", "moneybee_health", {})
        else:
            bridge = await self.xmlrpc_call("crm.lead", "moneybee_health", [])
        return {"provider": self.name, "mode": selected_mode, "bridge": bridge}
