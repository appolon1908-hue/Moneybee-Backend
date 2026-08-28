from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./smoke-moneybee.db")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")
os.environ.setdefault("LOCAL_IDENTITY_ENFORCEMENT", "false")


def _remove_local_smoke_db() -> None:
    url = os.environ["DATABASE_URL"]
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return
    database_path = url.removeprefix(prefix)
    if database_path in {"", ":memory:"}:
        return
    path = Path(database_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if path.name.startswith("smoke-moneybee") and path.suffix in {".db", ".sqlite"}:
        path.unlink(missing_ok=True)


_remove_local_smoke_db()

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@dataclass
class SmokeResult:
    name: str
    status: str
    detail: str


def _ok(name: str, detail: str = "ok") -> SmokeResult:
    return SmokeResult(name, "PASS", detail)


def _skip(name: str, detail: str) -> SmokeResult:
    return SmokeResult(name, "SKIP", detail)


def _fail(name: str, detail: str) -> SmokeResult:
    return SmokeResult(name, "FAIL", detail)


def _expect(
    name: str,
    response,
    status_code: int,
    predicate: Callable[[Any], bool] | None = None,
) -> SmokeResult:
    if response.status_code != status_code:
        return _fail(name, f"expected {status_code}, got {response.status_code}: {response.text}")
    if predicate is not None:
        try:
            payload = response.json()
        except ValueError:
            return _fail(name, "response was not JSON")
        if not predicate(payload):
            return _fail(name, f"unexpected payload: {payload}")
    return _ok(name)


def _signature(body: bytes, timestamp: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _prequalification_payload(suffix: str, revenue: int = 50000) -> dict[str, Any]:
    return {
        "funding_amount": 75000,
        "currency": "USD",
        "use_of_funds": "WORKING_CAPITAL",
        "time_in_business_months": 24,
        "monthly_revenue": revenue,
        "business_name": "Smoke Test Transport",
        "first_name": "Smoke",
        "last_name": "Runner",
        "email": f"smoke-{suffix}@example.com",
        "phone": "+15555550123",
        "postal_code": "33101",
        "consents": [
            {
                "type": "APPLICATION_TERMS",
                "document_version": "v1",
                "accepted": True,
            }
        ],
        "marketing": {"landing_page": "smoke"},
    }


def smoke_health(client: TestClient) -> list[SmokeResult]:
    return [
        _expect("health.live", client.get("/health/live"), 200),
        _expect("health.ready", client.get("/health/ready"), 200),
    ]


def smoke_login_and_auth(client: TestClient) -> list[SmokeResult]:
    results = [
        _expect(
            "auth.me.local_principal",
            client.get("/api/v2/me"),
            200,
            lambda payload: payload["subject"] == "local-admin"
            and payload["is_active"] is True,
        ),
        _expect(
            "auth.bootstrap.fails_without_token",
            client.post("/api/v2/auth/bootstrap", headers={"Idempotency-Key": uuid.uuid4().hex}),
            401,
            lambda payload: payload["detail"]["code"] == "AUTHENTICATION_REQUIRED",
        ),
    ]
    token = os.getenv("MONEYBEE_SMOKE_ACCESS_TOKEN")
    if not token:
        results.append(
            _skip(
                "auth.bootstrap.real_token",
                "set MONEYBEE_SMOKE_ACCESS_TOKEN to smoke-test real OIDC account bootstrap",
            )
        )
        return results
    response = client.post(
        "/api/v2/auth/bootstrap",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": uuid.uuid4().hex,
        },
    )
    results.append(
        _expect(
            "auth.bootstrap.real_token",
            response,
            200,
            lambda payload: "user_id" in payload and "organization_id" in payload,
        )
    )
    return results


def smoke_public_prequalification(client: TestClient) -> list[SmokeResult]:
    suffix = uuid.uuid4().hex
    idempotency_key = uuid.uuid4().hex
    payload = _prequalification_payload(suffix)
    first = client.post(
        "/api/v2/public/prequalifications",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    replay = client.post(
        "/api/v2/public/prequalifications",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    conflict = client.post(
        "/api/v2/public/prequalifications",
        json=_prequalification_payload(suffix, revenue=90000),
        headers={"Idempotency-Key": idempotency_key},
    )
    return [
        _expect("public.prequalification.accepted", first, 202, lambda payload: "lead_id" in payload),
        _expect("public.prequalification.replay", replay, 202, lambda payload: payload == first.json()),
        _expect(
            "public.prequalification.conflict",
            conflict,
            409,
            lambda payload: payload["detail"]["code"] == "IDEMPOTENCY_KEY_CONFLICT",
        ),
    ]


def smoke_webhooks(client: TestClient) -> list[SmokeResult]:
    secret = "smoke-webhook-secret"
    original_allowlist = settings.provider_webhook_allowlist_csv
    original_secrets = settings.provider_webhook_secrets_json
    settings.provider_webhook_allowlist_csv = "lender"
    settings.provider_webhook_secrets_json = json.dumps({"lender": secret})
    try:
        event_id = f"evt-smoke-{time.time_ns()}"
        body = json.dumps(
            {
                "event_id": event_id,
                "event_type": "submission.status_changed",
                "application_id": "smoke-application",
            },
            separators=(",", ":"),
        ).encode()
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-MoneyBee-Timestamp": timestamp,
            "X-MoneyBee-Signature": _signature(body, timestamp, secret),
        }
        first = client.post("/api/v2/webhooks/lenders/00000000-0000-0000-0000-000000000001", content=body, headers=headers)
        duplicate = client.post("/api/v2/webhooks/lenders/00000000-0000-0000-0000-000000000001", content=body, headers=headers)
        invalid = client.post(
            "/api/v2/webhooks/lenders/00000000-0000-0000-0000-000000000001",
            content=body,
            headers={**headers, "X-MoneyBee-Signature": "sha256=invalid"},
        )
        return [
            _expect("webhook.lender.accepted", first, 202, lambda payload: payload["duplicate"] is False),
            _expect("webhook.lender.duplicate", duplicate, 202, lambda payload: payload["duplicate"] is True),
            _expect("webhook.lender.invalid_signature", invalid, 401),
        ]
    finally:
        settings.provider_webhook_allowlist_csv = original_allowlist
        settings.provider_webhook_secrets_json = original_secrets


def smoke_capability_gates(client: TestClient) -> list[SmokeResult]:
    application_id = uuid.uuid4()
    return [
        _expect(
            "capability.bank_link.fail_closed",
            client.post(f"/api/v2/applications/{application_id}/bank/link-session"),
            503,
            lambda payload: payload["detail"]["code"] == "CAPABILITY_UNAVAILABLE",
        ),
        _expect(
            "capability.effective_flags.available",
            client.get("/api/v2/me/capabilities"),
            200,
            lambda payload: isinstance(payload, dict),
        ),
    ]


def smoke_openapi_surface(client: TestClient) -> list[SmokeResult]:
    response = client.get("/openapi.json")
    if response.status_code != 200:
        return [_fail("openapi.load", f"expected 200, got {response.status_code}")]
    paths = set(response.json().get("paths", {}))
    results = [
        _ok("openapi.load", f"{len(paths)} paths"),
        _ok("openapi.webhooks.present")
        if any("/api/v2/webhooks/" in path for path in paths)
        else _fail("openapi.webhooks.present", "no provider webhook paths found"),
    ]
    optional_surfaces = {
        "realtime": ("realtime", "websocket", "stream"),
        "market_data": ("market", "quote", "ticker", "price"),
        "trading": ("trading", "trade", "order"),
    }
    for surface, needles in optional_surfaces.items():
        matching = [path for path in paths if any(needle in path.lower() for needle in needles)]
        if matching:
            results.append(_ok(f"openapi.{surface}.present", f"{len(matching)} paths"))
        else:
            results.append(_skip(f"openapi.{surface}.present", "surface is not implemented in this Moneybee API"))
    return results


def run_smoke() -> list[SmokeResult]:
    with TestClient(app) as client:
        return [
            *smoke_health(client),
            *smoke_login_and_auth(client),
            *smoke_public_prequalification(client),
            *smoke_webhooks(client),
            *smoke_capability_gates(client),
            *smoke_openapi_surface(client),
        ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test critical MoneyBee API surfaces.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    results = run_smoke()
    failed = [item for item in results if item.status == "FAIL"]
    if args.json:
        print(json.dumps([item.__dict__ for item in results], indent=2, sort_keys=True))
    else:
        for item in results:
            print(f"{item.status:<4} {item.name} - {item.detail}")
        print(
            f"SMOKE_SUMMARY pass={sum(item.status == 'PASS' for item in results)} "
            f"skip={sum(item.status == 'SKIP' for item in results)} "
            f"fail={len(failed)}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
