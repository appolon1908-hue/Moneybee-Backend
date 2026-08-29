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


def _create_submitted_application_with_submission(client: TestClient) -> dict[str, str]:
    suffix = uuid.uuid4().hex
    lender_id = str(uuid.uuid4())
    lead = client.post(
        "/api/v2/public/prequalifications",
        json=_prequalification_payload(suffix, revenue=42000),
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    lead.raise_for_status()
    application = client.post(
        "/api/v2/applications",
        json={"lead_id": lead.json()["lead_id"]},
    )
    application.raise_for_status()
    application_id = application.json()["id"]
    business = client.put(
        f"/api/v2/applications/{application_id}/business",
        json={
            "legal_name": "Smoke Portal Logistics LLC",
            "entity_type": "LLC",
            "state_formed": "FL",
            "industry": "TRANSPORTATION",
            "address": {"state": "FL"},
        },
    )
    business.raise_for_status()
    financials = client.put(
        f"/api/v2/applications/{application_id}/financial-profile",
        json={
            "annual_revenue": 504000,
            "monthly_revenue": 42000,
            "monthly_expenses": 21000,
            "existing_debt": 0,
            "existing_positions": 0,
        },
    )
    financials.raise_for_status()
    owner = client.post(
        f"/api/v2/applications/{application_id}/owners",
        json={
            "first_name": "Smoke",
            "last_name": "Owner",
            "ownership_percent": 100,
            "address": {"state": "FL"},
        },
    )
    owner.raise_for_status()
    submitted = client.post(f"/api/v2/applications/{application_id}/submit")
    submitted.raise_for_status()
    program = client.post(
        f"/api/v2/lenders/{lender_id}/programs",
        json={
            "lender_id": lender_id,
            "name": "Smoke Working Capital",
            "product_type": "WORKING_CAPITAL",
            "min_amount": 10000,
            "max_amount": 125000,
            "minimum_monthly_revenue": 10000,
            "minimum_time_in_business_months": 12,
            "states": [],
            "excluded_industries": [],
        },
    )
    program.raise_for_status()
    matched = client.post(f"/api/v2/applications/{application_id}/match")
    matched.raise_for_status()
    submissions = client.post(
        f"/api/v2/admin/applications/{application_id}/prepare-matched-submissions"
    )
    submissions.raise_for_status()
    submission = submissions.json()[0]
    return {
        "application_id": application_id,
        "lender_id": lender_id,
        "program_id": submission["program_id"],
        "submission_id": submission["id"],
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


def smoke_portal_workflows(client: TestClient) -> list[SmokeResult]:
    try:
        ids = _create_submitted_application_with_submission(client)
    except Exception as exc:  # pragma: no cover - reported as smoke failure
        return [_fail("portal.seed_application_submission", str(exc))]

    application_id = ids["application_id"]
    submission_id = ids["submission_id"]
    lender_id = ids["lender_id"]
    program_id = ids["program_id"]
    results = [
        _expect(
            "portal.auth_context.available",
            client.get("/api/v2/auth/context"),
            200,
            lambda payload: "active_organization_id" in payload and "permissions" in payload,
        ),
        _expect(
            "portal.navigation.available",
            client.get("/api/v2/portal/navigation"),
            200,
            lambda payload: isinstance(payload, list) and len(payload) > 0,
        ),
        _expect(
            "portal.borrower_workspace.available",
            client.get("/api/v2/borrower/overview"),
            200,
            lambda payload: isinstance(payload.get("applications"), list),
        ),
        _expect(
            "portal.lender_workspace.available",
            client.get("/api/v2/lender/workspace"),
            200,
            lambda payload: payload["summary"]["submission_count"] >= 1,
        ),
        _expect(
            "portal.admin_workspace.available",
            client.get("/api/v2/admin/workspace"),
            200,
            lambda payload: "metrics" in payload and "work_queue" in payload,
        ),
        _expect(
            "portal.lender_submissions.available",
            client.get("/api/v2/lender/submissions"),
            200,
            lambda payload: any(item["id"] == submission_id for item in payload),
        ),
    ]

    submission_workspace = client.get(f"/api/v2/lender/submissions/{submission_id}/workspace")
    results.append(
        _expect(
            "portal.lender_submission_workspace.available",
            submission_workspace,
            200,
            lambda payload: payload["submission"]["id"] == submission_id,
        )
    )
    condition = client.post(
        f"/api/v2/lender/submissions/{submission_id}/conditions",
        json={"description": "Smoke-test borrower condition request"},
    )
    results.append(
        _expect(
            "portal.lender_condition.create",
            condition,
            201,
            lambda payload: payload["status"] == "BORROWER_ACTION_REQUIRED",
        )
    )
    condition_id = condition.json().get("id") if condition.status_code == 201 else ""
    results.extend(
        [
            _expect(
                "portal.borrower_conditions.list",
                client.get(f"/api/v2/applications/{application_id}/conditions"),
                200,
                lambda payload: any(item["id"] == condition_id for item in payload),
            ),
            _expect(
                "portal.borrower_condition.submit",
                client.post(f"/api/v2/conditions/{condition_id}/submit"),
                200,
                lambda payload: payload["status"] == "SUBMITTED",
            ),
        ]
    )

    offer = client.post(
        f"/api/v2/lender/submissions/{submission_id}/offers",
        json={
            "application_id": application_id,
            "lender_id": lender_id,
            "program_id": program_id,
            "product_type": "WORKING_CAPITAL",
            "amount": 50000,
            "term_months": 12,
            "payment_frequency": "MONTHLY",
            "payment_amount": 4800,
            "apr": 14,
            "origination_fee": 500,
            "total_repayment": 57600,
        },
    )
    results.append(
        _expect(
            "portal.lender_offer.create",
            offer,
            201,
            lambda payload: payload["status"] == "AVAILABLE",
        )
    )
    offer_id = offer.json().get("id") if offer.status_code == 201 else ""
    application = client.get(f"/api/v2/applications/{application_id}")
    expected_version = application.json().get("version") if application.status_code == 200 else None
    results.extend(
        [
            _expect(
                "portal.borrower_offers.list",
                client.get(f"/api/v2/applications/{application_id}/offers"),
                200,
                lambda payload: any(item["id"] == offer_id for item in payload),
            ),
            _expect(
                "portal.borrower_offer.accept",
                client.post(
                    f"/api/v2/offers/{offer_id}/accept",
                    headers={
                        "Idempotency-Key": uuid.uuid4().hex,
                        "If-Match": f'"{expected_version}"',
                    },
                ),
                200,
                lambda payload: payload["status"] == "ACCEPTED",
            ),
        ]
    )
    return results


def smoke_admin_operational_surfaces(client: TestClient) -> list[SmokeResult]:
    list_checks = {
        "admin.crm_events": "/api/v2/admin/crm/events",
        "admin.capabilities": "/api/v2/admin/capabilities",
        "admin.provider_connections": "/api/v2/admin/provider-connections",
        "admin.fundings": "/api/v2/admin/fundings",
        "admin.complaints": "/api/v2/admin/complaints",
        "admin.integration_events": "/api/v2/admin/integration-events",
        "admin.reconciliation_runs": "/api/v2/admin/reconciliation-runs",
        "admin.catalog.leads": "/api/v2/admin/catalog/leads",
        "admin.catalog.applications": "/api/v2/admin/catalog/applications",
        "admin.catalog.programs": "/api/v2/admin/catalog/programs",
        "admin.catalog.submissions": "/api/v2/admin/catalog/submissions",
        "admin.catalog.offers": "/api/v2/admin/catalog/offers",
        "admin.catalog.matches": "/api/v2/admin/catalog/matches",
        "admin.underwriting_reviews": "/api/v2/admin/underwriting/reviews",
        "admin.sla_alerts": "/api/v2/admin/sla-alerts",
        "admin.users": "/api/v2/admin/users",
        "admin.integration_inbox": "/api/v2/admin/integration-inbox",
        "admin.operational_exceptions": "/api/v2/admin/operational-exceptions",
    }
    results = [
        _expect(
            "admin.dashboard",
            client.get("/api/v2/admin/dashboard"),
            200,
            lambda payload: isinstance(payload, dict),
        ),
        _expect(
            "admin.integration_control_plane",
            client.get("/api/v2/admin/integration-control-plane"),
            200,
            lambda payload: isinstance(payload, dict),
        ),
        _expect(
            "admin.system_readiness",
            client.get("/api/v2/admin/system/readiness"),
            200,
            lambda payload: "FINAL_STATUS" in payload,
        ),
    ]
    for name, path in list_checks.items():
        results.append(
            _expect(
                name,
                client.get(path),
                200,
                lambda payload: isinstance(payload, list),
            )
        )
    return results


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
            *smoke_portal_workflows(client),
            *smoke_admin_operational_surfaces(client),
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
