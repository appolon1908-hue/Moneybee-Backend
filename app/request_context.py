from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from fastapi import HTTPException, Request

from app.config import settings


PortalName = Literal["borrower", "lender", "admin"]


@dataclass(frozen=True)
class RequestIdentifiers:
    request_id: str
    correlation_id: str


def problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def request_identifiers(request: Request) -> RequestIdentifiers:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    correlation_id = request.headers.get("X-Correlation-ID") or request_id
    return RequestIdentifiers(
        request_id=request_id[:160],
        correlation_id=correlation_id[:160],
    )


def token_client_id(claims: Mapping[str, Any]) -> str:
    return str(claims.get("azp") or claims.get("client_id") or "").strip()


def _portals_for_path(path: str) -> frozenset[PortalName] | None:
    normalized = path.rstrip("/") or "/"
    if normalized == "/api/v2/borrower" or normalized.startswith("/api/v2/borrower/"):
        return frozenset({"borrower"})
    if (
        normalized == "/api/v2/lender"
        or normalized.startswith("/api/v2/lender/")
        or normalized == "/api/v2/lenders"
        or normalized.startswith("/api/v2/lenders/")
    ):
        return frozenset({"lender"})
    if (
        normalized == "/api/v2/admin"
        or normalized.startswith("/api/v2/admin/")
        or normalized == "/api/v2/finance"
        or normalized.startswith("/api/v2/finance/")
    ):
        return frozenset({"admin"})
    if normalized == "/api/v2/applications" or normalized.startswith(
        "/api/v2/applications/"
    ):
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
    allowed_portals = _portals_for_path(path)
    client_id = token_client_id(claims)
    if allowed_portals is None:
        return client_id

    configured = settings.portal_client_ids
    allowed_client_ids = frozenset(
        candidate
        for portal in allowed_portals
        for candidate in configured[portal]
    )
    if not client_id or client_id not in allowed_client_ids:
        expected = ", ".join(sorted(allowed_portals))
        raise problem(
            "PORTAL_TOKEN_MISMATCH",
            f"This access token was not issued to an approved {expected} portal client.",
            403,
        )
    return client_id
