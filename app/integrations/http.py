import asyncio
from typing import Any

import httpx

from app.config import settings
from app.integrations.base import ProviderError


RETRYABLE_STATUS = {429, 500, 502, 503, 504}


async def provider_request(
    *,
    provider: str,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json: dict | None = None,
    data: dict | None = None,
    content: bytes | str | None = None,
    auth: tuple[str, str] | None = None,
    retries: int = 2,
) -> Any:
    if sum(value is not None for value in (json, data, content)) > 1:
        raise ValueError("Only one of json, data, or content may be supplied")

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(
                timeout=settings.provider_timeout_seconds
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    data=data,
                    content=content,
                    auth=auth,
                )
        except httpx.HTTPError as exc:
            if attempt < retries:
                await asyncio.sleep(min(2 ** (attempt + 1), 5))
                continue
            raise ProviderError(provider, "Provider connection failed") from exc

        if response.status_code in RETRYABLE_STATUS and attempt < retries:
            await asyncio.sleep(min(2 ** (attempt + 1), 5))
            continue
        if not response.is_success:
            raise ProviderError(
                provider,
                "Provider request failed",
                status_code=response.status_code,
            )
        if not response.content:
            return {"status_code": response.status_code}
        try:
            return response.json()
        except ValueError:
            return {
                "status_code": response.status_code,
                "text": response.text[:1000],
            }

    raise ProviderError(provider, "Provider retry budget exhausted")