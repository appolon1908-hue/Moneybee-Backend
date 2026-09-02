from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import HTTPException


PortalName = Literal["borrower", "lender", "admin"]

_DEFAULTS: dict[PortalName, str] = {
    "borrower": "moneybee-borrower",
    "lender": "moneybee-lender",
    "admin": "moneybee-admin",
}
_ENV_NAMES: dict[PortalName, str] = {
    "borrower": "BORROWER_OIDC_CLIENT_IDS",
    "lender": "LENDER_OIDC_CLIENT_IDS",
    "admin": "ADMIN_OIDC_CLIENT_IDS",
}


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _csv(name: str, default: str) -> frozenset[str]:
    raw = os.getenv(name, default)
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def portal_client_ids() -> dict[PortalName, frozenset[str]]:
    values = {
        portal: _csv(_ENV_NAMES[portal], _DEFAULTS[portal])
        for portal in _DEFAULTS
    }
    if any(not client_ids for client_ids in values.values()):
        raise _problem(
            "PORTAL_CLIENT_CONFIGURATION_INVALID",
            "Every MoneyBee portal must have at least one configured Keycloak client ID.",
            503,
        )
    pairs = (("borrower", "lender"), ("borrower", "admin"), ("lender", "admin"))
    for left, right in pairs:
        overlap = values[left] & values[right]
        if overlap:
            raise _problem(
                "PORTAL_CLIENT_CONFIGURATION_INVALID",
                "Borrower, lender, and administrator Keycloak client IDs must be distinct.",
                503,
            )
    return values


def self_registration_client_ids() -> frozenset[str]:
    configured = _csv("ACCOUNT_SELF_REGISTRATION_CLIENT_IDS", "moneybee-borrower")
    borrower_clients = portal_client_ids()["borrower"]
    if not configured or not configured.issubset(borrower_clients):
        raise _problem(
            "PORTAL_CLIENT_CONFIGURATION_INVALID",
            "Self-registration client IDs must be a non-empty subset of borrower client IDs.",
            503,
        )
    return configured


def token_client_id(claims: Mapping[str, Any]) -> str:
    return str(claims.get("azp") or claims.get("client_id") or "").strip()


def _portal_names_for_path(path: str) -> frozenset[PortalName] | None:
    normalized = path.rstrip("/") or "/"
    if normalized == "/api/v2/auth/bootstrap":
        return frozenset({"borrower"})
    if normalized == "/api/v2/borrower" or normalized.startswith("/api/v2/borrower/"):
        return frozenset({"borrower"})
    if (
        normalized == "/api/v2/lender"
        or normalized.startswith("/api/v2/lender/")
        or normalized == "/api/v2/lenders"
        or normalized.startswith("/api/v2/lenders/")
    ):
        return frozenset({"lender"})
    if normalized == "/api/v2/admin" or normalized.startswith("/api/v2/admin/"):
        return frozenset({"admin"})
    if normalized == "/api/v2/applications" or normalized.startswith("/api/v2/applications/"):
        return frozenset({"borrower", "admin"})
    if normalized.startswith("/api/v2/offers/") and (
        normalized.endswith("/accept")
        or "/commercial-financing-disclosure" in normalized
    ):
        return frozenset({"borrower"})
    if normalized.startswith("/api/v2/conditions/") and normalized.endswith("/submit"):
        return frozenset({"borrower"})
    return None


def enforce_portal_client(path: str, claims: Mapping[str, Any]) -> str:
    client_id = token_client_id(claims)
    allowed_portals = _portal_names_for_path(path)
    if allowed_portals is None:
        return client_id

    configured = portal_client_ids()
    allowed_client_ids = frozenset(
        client_id_value
        for portal in allowed_portals
        for client_id_value in configured[portal]
    )
    if not client_id or client_id not in allowed_client_ids:
        expected = ", ".join(sorted(allowed_portals))
        raise _problem(
            "PORTAL_TOKEN_MISMATCH",
            f"This access token was not issued to an approved {expected} portal client.",
            403,
        )
    return client_id
