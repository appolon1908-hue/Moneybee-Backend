from __future__ import annotations

from pathlib import Path
import tomllib

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.integrations.base import ProviderError
from app.integrations.codestra_sdk import MoneyBeeCodestraCommands


SDK_SHA = "fd9a5c3fd49534a7f7492a452f53815c386687b9"


def test_sdk_is_pinned_to_exact_reviewed_commit() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependency = next(
        item
        for item in project["project"]["dependencies"]
        if item.startswith("codestra-moneybee-connectors")
    )
    assert f"@{SDK_SHA}" in dependency
    assert "@development" not in dependency
    assert "@main" not in dependency
    assert project["tool"]["hatch"]["metadata"]["allow-direct-references"] is True


def test_context_requires_release_provenance(monkeypatch) -> None:
    monkeypatch.setattr(settings, "source_sha", None)
    with pytest.raises(ProviderError, match="SOURCE_SHA"):
        MoneyBeeCodestraCommands.context(
            tenant_id="tenant",
            principal="worker",
            request_id="request",
            correlation_id="correlation",
            operation_id="operation",
            idempotency_key="idempotency-key",
        )


@pytest.mark.asyncio
async def test_sdk_capability_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "source_sha", "release-sha")
    monkeypatch.setattr(
        settings,
        "codestra_middleware_base_url",
        "https://middleware.example",
    )
    monkeypatch.setattr(settings, "codestra_sdk_enabled", False)
    monkeypatch.setattr(settings, "codestra_sdk_capabilities_csv", "")
    context = MoneyBeeCodestraCommands.context(
        tenant_id="tenant",
        principal="worker",
        request_id="request",
        correlation_id="correlation",
        operation_id="operation",
        idempotency_key="idempotency-key",
    )
    with pytest.raises(ProviderError, match="disabled"):
        await MoneyBeeCodestraCommands().submit_crm_projection(context, {"id": "one"})


def test_staging_rejects_sdk_without_codestra_provider_and_capability_allowlist() -> None:
    secure = {
        "_env_file": None,
        "app_env": "staging",
        "auto_create_schema": False,
        "local_auth_bypass": False,
        "local_identity_enforcement": True,
        "source_sha": "1" * 40,
        "codestra_sdk_enabled": True,
    }
    with pytest.raises(ValidationError, match="MIDDLEWARE_PROVIDER=codestra"):
        Settings(**secure)

    with pytest.raises(ValidationError, match="capability allowlist"):
        Settings(
            **secure,
            middleware_provider="codestra",
            codestra_middleware_base_url="https://moneybee-events.codestra.co",
            codestra_middleware_token_url=(
                "https://auth.codestra.co/realms/codestra/protocol/openid-connect/token"
            ),
            codestra_middleware_client_id="moneybee-service",
            codestra_middleware_client_secret="test-secret",
        )


def test_staging_accepts_explicit_sdk_configuration_without_enabling_live_writes() -> None:
    configured = Settings(
        _env_file=None,
        app_env="staging",
        auto_create_schema=False,
        local_auth_bypass=False,
        local_identity_enforcement=True,
        source_sha="1" * 40,
        middleware_provider="codestra",
        codestra_middleware_base_url="https://moneybee-events.codestra.co",
        codestra_middleware_token_url=(
            "https://auth.codestra.co/realms/codestra/protocol/openid-connect/token"
        ),
        codestra_middleware_client_id="moneybee-service",
        codestra_middleware_client_secret="test-secret",
        codestra_sdk_enabled=True,
        codestra_sdk_capabilities_csv="ODOO_WRITE",
    )
    assert configured.codestra_sdk_enabled is True
    assert configured.codestra_sdk_capabilities == frozenset({"ODOO_WRITE"})
    assert configured.live_writes is False
    assert configured.odoo_write is False


def test_container_builds_preserve_application_owned_proxy_policy() -> None:
    root_dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    release_dockerfile = Path("docker/Dockerfile.release").read_text(encoding="utf-8")
    for content in (root_dockerfile, release_dockerfile):
        assert "--no-proxy-headers" in content
        assert "--forwarded-allow-ips=*" not in content
    assert "apt-get purge -y --auto-remove git" in root_dockerfile
    assert "FROM ${PYTHON_BASE_IMAGE} AS wheel" in release_dockerfile
