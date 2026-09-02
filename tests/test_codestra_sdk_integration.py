from __future__ import annotations

import pytest

from app.config import settings
from app.integrations.base import ProviderError
from app.integrations.codestra_sdk import MoneyBeeCodestraCommands


def test_sdk_is_pinned_to_exact_commit() -> None:
    dependency = next(
        item for item in __import__("tomllib").loads(open("pyproject.toml", "rb").read().decode())["project"]["dependencies"]
        if item.startswith("codestra-moneybee-connectors")
    )
    assert "@fdde064c8eb151eff7a154c79943273e5c45c970" in dependency
    assert "@development" not in dependency and "@main" not in dependency


def test_context_requires_release_provenance(monkeypatch) -> None:
    monkeypatch.setattr(settings, "source_sha", None)
    with pytest.raises(ProviderError, match="SOURCE_SHA"):
        MoneyBeeCodestraCommands.context(
            tenant_id="tenant", principal="worker", request_id="request",
            correlation_id="correlation", operation_id="operation",
            idempotency_key="idempotency-key",
        )


@pytest.mark.asyncio
async def test_sdk_capability_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "source_sha", "release-sha")
    monkeypatch.setattr(settings, "codestra_middleware_base_url", "https://middleware.example")
    monkeypatch.setattr(settings, "codestra_sdk_enabled", False)
    context = MoneyBeeCodestraCommands.context(
        tenant_id="tenant", principal="worker", request_id="request",
        correlation_id="correlation", operation_id="operation",
        idempotency_key="idempotency-key",
    )
    with pytest.raises(ProviderError, match="disabled"):
        await MoneyBeeCodestraCommands().submit_crm_projection(context, {"id": "one"})
