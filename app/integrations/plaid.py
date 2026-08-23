import hashlib
import hmac
import time

import jwt
from jwt import PyJWK

from app.config import settings
from app.integrations.base import ProviderError
from app.integrations.http import provider_request


class PlaidAdapter:
    name = "plaid"

    def _credentials(self) -> dict:
        if not settings.plaid_client_id or not settings.plaid_secret:
            raise ProviderError("plaid", "Plaid credentials are not configured")
        return {
            "client_id": settings.plaid_client_id,
            "secret": settings.plaid_secret,
        }

    def _url(self, path: str) -> str:
        return settings.plaid_base_url.rstrip("/") + path

    async def _post(self, path: str, payload: dict) -> dict:
        result = await provider_request(
            provider="plaid",
            method="POST",
            url=self._url(path),
            json={**self._credentials(), **payload},
            retries=1,
        )
        if not isinstance(result, dict):
            raise ProviderError("plaid", "Unexpected provider response")
        return result

    async def create_link_session(self, application_id: str) -> dict:
        payload: dict = {
            "user": {"client_user_id": application_id},
            "client_name": settings.plaid_client_name,
            "products": settings.plaid_products,
            "country_codes": settings.plaid_country_codes,
            "language": "en",
        }
        if settings.plaid_webhook_url:
            payload["webhook"] = settings.plaid_webhook_url
        if settings.plaid_redirect_uri:
            payload["redirect_uri"] = settings.plaid_redirect_uri
        result = await self._post("/link/token/create", payload)
        return {
            "provider": self.name,
            "link_token": result["link_token"],
            "expiration": result.get("expiration"),
        }

    async def exchange_public_token(self, public_token: str) -> dict:
        result = await self._post(
            "/item/public_token/exchange",
            {"public_token": public_token},
        )
        return {
            "access_token": result["access_token"],
            "item_id": result["item_id"],
            "request_id": result.get("request_id"),
        }

    async def get_accounts(self, access_token: str) -> dict:
        return await self._post(
            "/accounts/get",
            {"access_token": access_token},
        )

    async def sync_transactions(
        self,
        access_token: str,
        cursor: str | None,
    ) -> dict:
        added: list[dict] = []
        modified: list[dict] = []
        removed: list[dict] = []
        next_cursor = cursor or ""
        while True:
            result = await self._post(
                "/transactions/sync",
                {
                    "access_token": access_token,
                    "cursor": next_cursor,
                    "count": 500,
                },
            )
            added.extend(result.get("added", []))
            modified.extend(result.get("modified", []))
            removed.extend(result.get("removed", []))
            next_cursor = result.get("next_cursor") or next_cursor
            if not result.get("has_more", False):
                break
        return {
            "added": added,
            "modified": modified,
            "removed": removed,
            "next_cursor": next_cursor,
        }

    async def remove_item(self, access_token: str) -> None:
        await self._post("/item/remove", {"access_token": access_token})

    async def _webhook_key(self, key_id: str) -> dict:
        result = await self._post(
            "/webhook_verification_key/get",
            {"key_id": key_id},
        )
        return result["key"]

    async def verify_webhook(
        self,
        body: bytes,
        signed_token: str | None,
    ) -> bool:
        if not signed_token:
            return False
        try:
            header = jwt.get_unverified_header(signed_token)
            if header.get("alg") != "ES256" or not header.get("kid"):
                return False
            jwk_data = await self._webhook_key(str(header["kid"]))
            key = PyJWK.from_dict(jwk_data).key
            claims = jwt.decode(
                signed_token,
                key,
                algorithms=["ES256"],
                options={"verify_aud": False},
            )
            issued_at = int(claims["iat"])
            claimed_hash = str(claims["request_body_sha256"])
        except (KeyError, TypeError, ValueError, jwt.PyJWTError, ProviderError):
            return False
        if abs(int(time.time()) - issued_at) > 300:
            return False
        actual_hash = hashlib.sha256(body).hexdigest()
        return hmac.compare_digest(actual_hash, claimed_hash)
