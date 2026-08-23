import hashlib
import hmac

from app.config import settings
from app.integrations.base import ProviderError
from app.integrations.http import provider_request


class MiddeskAdapter:
    name = "middesk"

    def _headers(self) -> dict[str, str]:
        if not settings.middesk_api_key:
            raise ProviderError("middesk", "MIDDESK_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {settings.middesk_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def verify_business(self, payload: dict) -> dict:
        body = {
            "name": payload["business_name"],
            "addresses": [payload["address"]],
            "external_id": payload["application_id"],
            "unique_external_id": payload["application_id"],
        }
        if payload.get("ein"):
            body["tin"] = {"tin": payload["ein"]}
        if payload.get("website"):
            body["website"] = {"url": payload["website"]}
        if payload.get("owners"):
            body["people"] = [
                {
                    "name": f"{owner['first_name']} {owner['last_name']}",
                    "titles": [owner.get("title") or "Owner"],
                }
                for owner in payload["owners"]
            ]
        result = await provider_request(
            provider=self.name,
            method="POST",
            url=settings.middesk_base_url.rstrip("/") + "/v1/businesses",
            headers=self._headers(),
            json=body,
        )
        if not isinstance(result, dict):
            raise ProviderError(self.name, "Business response was invalid")
        return self.normalize(result)

    def normalize(self, result: dict) -> dict:
        status_map = {
            "open": "PENDING",
            "pending": "PENDING",
            "in_audit": "PENDING",
            "in_review": "REVIEW_REQUIRED",
            "approved": "VERIFIED",
            "rejected": "FAILED",
        }
        provider_status = str(result.get("status") or "open")
        flags = []
        if provider_status == "rejected":
            flags.append("MIDDESK_REJECTED")
        watchlist = result.get("watchlist") or {}
        if isinstance(watchlist, dict) and watchlist.get("hits"):
            flags.append("WATCHLIST_HIT")
        return {
            "provider": self.name,
            "provider_reference": result.get("id"),
            "status": status_map.get(provider_status, "REVIEW_REQUIRED"),
            "normalized_result": {
                "provider_status": provider_status,
                "review_tasks": (result.get("review") or {}).get("tasks", []),
                "tin": result.get("tin"),
                "formation": result.get("formation"),
                "registrations": result.get("registrations", []),
                "watchlist": watchlist,
                "risk": result.get("risk") or {},
                "risk_flags": flags,
            },
        }

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool:
        if not settings.middesk_webhook_secret or not signature:
            return False
        expected = hmac.new(
            settings.middesk_webhook_secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature.removeprefix("sha256="))

