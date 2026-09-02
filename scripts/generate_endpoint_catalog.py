"""Generate the MoneyBee endpoint URL and behavior catalog from FastAPI OpenAPI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


TARGET = ROOT / "docs" / "API_ENDPOINT_CATALOG.md"
API_ORIGIN = "https://api.moneybeeloan.com"
CANONICAL_PREFIX = "/api/v2"
LEGACY_PREFIX = "/api/v1"


def _method_order(method: str) -> int:
    return ["get", "post", "put", "patch", "delete", "options"].index(method)


def _route_scope(path: str) -> str:
    if path.startswith("/api/v2/public/"):
        return "Public intake"
    if path.startswith("/api/v2/webhooks/"):
        return "Provider webhook"
    if path.startswith("/api/v2/auth/") or path.startswith("/api/v2/me"):
        return "Identity/session"
    if path.startswith("/api/v2/borrower/"):
        return "Borrower portal"
    if path.startswith("/api/v2/lender/") or path.startswith("/api/v2/lenders/"):
        return "Lender portal"
    if path.startswith("/api/v2/admin/"):
        return "Admin/operations"
    if path.startswith("/api/v2/finance/"):
        return "Finance"
    if path.startswith("/api/v2/applications/") or path == "/api/v2/applications":
        return "Application workflow"
    if path.startswith("/api/v2/offers/"):
        return "Offers"
    if path.startswith("/health/"):
        return "Health"
    return "Core API"


def _auth_model(path: str) -> str:
    if path.startswith("/health/"):
        return "None"
    if path.startswith("/api/v2/public/"):
        return "No bearer token; idempotency key required on writes"
    if path.startswith("/api/v2/webhooks/"):
        return "Provider HMAC headers"
    return "OIDC bearer token plus local MoneyBee principal"


def _rate_limit(path: str) -> str:
    if path.startswith("/api/v2/public/"):
        return "Public intake fixed-window limit"
    if path.startswith("/api/v2/webhooks/"):
        return "Webhook fixed-window limit"
    return "None in app middleware"


def _idempotency(path: str, method: str) -> str:
    if method not in {"post", "put", "patch", "delete"}:
        return "N/A"
    if path.startswith("/api/v2/public/"):
        return "`Idempotency-Key` hashes and replays matching payloads"
    if path.startswith("/api/v2/webhooks/"):
        return "Provider event/message ID plus payload hash"
    if "accept" in path or "requeue" in path or "bootstrap" in path:
        return "`Idempotency-Key` required or supported"
    return "Domain-specific transition guards"


def _logic(operation: dict[str, Any], path: str) -> str:
    summary = str(operation.get("summary") or "").strip()
    if summary:
        return summary
    operation_id = str(operation.get("operationId") or "").strip()
    if operation_id:
        return operation_id.replace("_", " ")
    return _route_scope(path)


def _rows(schema: dict[str, Any]) -> list[tuple[str, str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith(CANONICAL_PREFIX) and not path.startswith("/health/"):
            continue
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options"}:
                continue
            rows.append(
                (
                    _route_scope(path),
                    method.upper(),
                    path,
                    f"{API_ORIGIN}{path}",
                    _auth_model(path),
                    _rate_limit(path),
                    f"{_idempotency(path, method)}; {_logic(operation, path)}",
                )
            )
    return sorted(rows, key=lambda item: (item[0], item[2], _method_order(item[1].lower())))


def render_catalog() -> str:
    schema = app.openapi()
    rows = _rows(schema)
    lines = [
        "# MoneyBee API endpoint catalog",
        "",
        "Generated from the FastAPI OpenAPI document. Do not edit endpoint rows by hand; run `python scripts/generate_endpoint_catalog.py`.",
        "",
        "## Runtime URLs",
        "",
        "| Surface | URL | Notes |",
        "| --- | --- | --- |",
        f"| Production API origin | `{API_ORIGIN}` | Hosted behind the MoneyBee edge. |",
        f"| Canonical REST API | `{API_ORIGIN}{CANONICAL_PREFIX}` | Browser frontends and integrations should use this prefix. |",
        f"| Legacy compatibility API | `{API_ORIGIN}{LEGACY_PREFIX}` | Runtime alias of `/api/v2`; hidden from OpenAPI and slated for deprecation headers. |",
        "| OpenAPI | `https://api.moneybeeloan.com/openapi.json` | Disabled docs UI in production, JSON contract remains the source of truth. |",
        "| Borrower portal | `https://app.moneybeeloan.com` | Uses `VITE_API_BASE_URL=https://api.moneybeeloan.com/api/v2`. |",
        "| Lender portal | `https://lenders.moneybeeloan.com` | Uses the canonical `/api/v2` base URL. |",
        "| Admin portal | `https://admin.moneybeeloan.com` | Uses the canonical `/api/v2` base URL. |",
        "| Marketing site | `https://moneybeeloan.com` | Public forms post only to MoneyBee `/api/v2/public/*`. |",
        "",
        "## Cross-cutting logic",
        "",
        "- Public intake writes require `Idempotency-Key`, are rate limited, store consent/evidence, and enqueue CRM/outbox work without exposing provider credentials.",
        "- Provider webhooks require HMAC signature headers, timestamp tolerance, configured provider secrets, bounded body size, payload-hash replay handling, durable inbox/receipt storage, and app-level rate limiting.",
        "- Authenticated portal routes require OIDC bearer tokens, a resolved local MoneyBee principal, portal/client boundary enforcement, tenant organization context, and permission checks.",
        "- `/api/v1` is a compatibility alias of `/api/v2` and is intentionally absent from OpenAPI.",
        "",
        "## Endpoints",
        "",
        "| Scope | Method | Path | Production URL | Auth | Rate limit | Logic |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for scope, method, path, url, auth, rate_limit, logic in rows:
        lines.append(
            f"| {scope} | `{method}` | `{path}` | `{url}` | {auth} | {rate_limit} | {logic} |"
        )
    lines.extend(
        [
            "",
            f"Total canonical endpoints: {len(rows)}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when the catalog is stale")
    args = parser.parse_args()

    rendered = render_catalog()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            raise SystemExit("docs/API_ENDPOINT_CATALOG.md is stale; regenerate it")
        print("Endpoint catalog verified")
        return 0

    TARGET.write_text(rendered, encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
