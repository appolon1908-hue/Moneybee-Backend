import hashlib
import json
import time

from app.config import settings
from app.integrations.base import ProviderError
from app.integrations.http import provider_request
from app.integrations.mapping import get_path, map_payload


class ExperianCommercialAdapter:
    """Contract-configured commercial-credit adapter.

    Endpoint paths and field mappings are deliberately not guessed; they must
    match the customer's Experian entitlement.
    """

    name = "experian"

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._expires_at = 0.0

    async def _token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        if not all(
            [
                settings.experian_token_url,
                settings.experian_client_id,
                settings.experian_client_secret,
            ]
        ):
            raise ProviderError(self.name, "OAuth client configuration is incomplete")
        data = {"grant_type": "client_credentials"}
        if settings.experian_scope:
            data["scope"] = settings.experian_scope
        auth = None
        if settings.experian_token_auth_style == "body":
            data["client_id"] = settings.experian_client_id
            data["client_secret"] = settings.experian_client_secret
        else:
            auth = (
                str(settings.experian_client_id),
                str(settings.experian_client_secret),
            )
        result = await provider_request(
            provider=self.name,
            method="POST",
            url=str(settings.experian_token_url),
            data=data,
            auth=auth,
            retries=1,
        )
        token = result.get("access_token") if isinstance(result, dict) else None
        if not token:
            raise ProviderError(self.name, "OAuth response did not contain access_token")
        self._access_token = str(token)
        self._expires_at = time.time() + int(result.get("expires_in", 3600))
        return self._access_token

    async def request_credit(self, canonical_payload: dict) -> dict:
        required = [
            settings.experian_base_url,
            settings.experian_business_search_path,
            settings.experian_business_report_path_template,
        ]
        if not all(required):
            raise ProviderError(
                self.name,
                "Endpoint paths must be configured from the Experian entitlement",
            )
        try:
            mapping = json.loads(settings.experian_search_mapping_json)
        except json.JSONDecodeError as exc:
            raise ProviderError(self.name, "Search mapping is not valid JSON") from exc
        if not mapping:
            raise ProviderError(
                self.name,
                "Search mapping must match the contracted request schema",
            )
        token = await self._token()
        search_result = await provider_request(
            provider=self.name,
            method="POST",
            url=(
                str(settings.experian_base_url).rstrip("/")
                + str(settings.experian_business_search_path)
            ),
            headers={"Authorization": f"Bearer {token}"},
            json=map_payload(canonical_payload, mapping),
        )
        business_id = get_path(search_result, settings.experian_search_id_path)
        if not business_id:
            raise ProviderError(self.name, "Configured business ID was not returned")
        report_path = str(settings.experian_business_report_path_template).format(
            business_id=business_id
        )
        report = await provider_request(
            provider=self.name,
            method="GET",
            url=str(settings.experian_base_url).rstrip("/") + report_path,
            headers={"Authorization": f"Bearer {token}"},
        )
        return {
            "provider": self.name,
            "provider_reference": str(business_id),
            "normalized_result": {
                "credit_score": get_path(report, settings.experian_score_path),
                "risk_class": get_path(report, settings.experian_risk_class_path),
                "bankruptcy_count": get_path(
                    report, settings.experian_bankruptcy_count_path
                ),
                "lien_count": get_path(report, settings.experian_lien_count_path),
                "judgment_count": get_path(
                    report, settings.experian_judgment_count_path
                ),
                "provider_response_hash": hashlib.sha256(
                    json.dumps(report, sort_keys=True, default=str).encode()
                ).hexdigest(),
            },
        }

