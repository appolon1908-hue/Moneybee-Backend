import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import settings
from app.main import app
from app.rate_limit import (
    InMemoryRateLimitMiddleware,
    _bucket_for_path,
    reset_rate_limit_state,
    resolved_client_ip,
)


def _request(peer: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers,
                    "client": (peer, 12345), "scheme": "http", "server": ("test", 80)})


def test_forwarded_for_is_ignored_from_an_untrusted_peer(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs_csv", "10.0.0.0/8")
    assert resolved_client_ip(_request("198.51.100.5", "203.0.113.8")) == "198.51.100.5"


def test_forwarded_chain_returns_rightmost_untrusted_hop(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs_csv", "10.0.0.0/8,192.0.2.0/24")
    request = _request("10.0.0.5", "198.51.100.7, 203.0.113.9, 192.0.2.44")
    assert resolved_client_ip(request) == "203.0.113.9"


def test_malformed_forwarded_chain_fails_closed_to_peer(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs_csv", "10.0.0.0/8")
    assert resolved_client_ip(_request("10.0.0.5", "203.0.113.9, garbage")) == "10.0.0.5"


def test_unhandled_exception_returns_problem_json_and_logs(caplog):
    boom_router = APIRouter()

    @boom_router.get("/api/v2/__test__/boom")
    async def boom():
        raise RuntimeError("kaboom")

    app.include_router(boom_router)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            with caplog.at_level("ERROR"):
                response = client.get(
                    "/api/v2/__test__/boom",
                    headers={"X-Request-ID": "test-boom-request"},
                )
    finally:
        app.router.routes = [
            route for route in app.router.routes if route not in boom_router.routes
        ]

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 500
    assert body["request_id"] == "test-boom-request"
    assert "kaboom" not in str(body)
    assert any("request.unhandled_exception" in record.message for record in caplog.records)


def test_request_completed_is_logged(caplog):
    with TestClient(app) as client:
        with caplog.at_level("INFO"):
            response = client.get("/health/live")

    assert response.status_code == 200
    assert any("request.completed" in record.message for record in caplog.records)


def test_api_v1_responses_carry_deprecation_and_sunset_headers():
    with TestClient(app) as client:
        v1_response = client.get("/api/v1/me")
        v2_response = client.get("/api/v2/me")

    assert v1_response.headers.get("Deprecation") == "true"
    assert "Sunset" in v1_response.headers
    assert v1_response.headers["Link"] == '</api/v2/me>; rel="successor-version"'
    assert "Deprecation" not in v2_response.headers
    assert "Sunset" not in v2_response.headers


def test_http_exceptions_converge_on_one_rfc7807_envelope_shape():
    """Every HTTPException in the codebase used to surface as one of three
    different shapes depending on where it was raised: RFC 7807 (validation/
    500s), {"detail": {"code","message"}} (auth/portal), or
    {"detail": {"code","from_status","to_status","allowed"}} (state-machine
    transitions, no message key at all). They all go through
    http_exception_problem() now - this checks a plain-string-detail 404,
    a {code,message}-detail 403, and a {code,...}-detail-without-message 409
    all land on the same top-level shape."""
    with TestClient(app) as client:
        not_found = client.get(
            "/api/v2/lender/submissions/00000000-0000-0000-0000-000000000000/workspace",
            headers={"Authorization": "Bearer local-test"},
        )

    assert not_found.status_code == 404
    body = not_found.json()
    assert not_found.headers["content-type"] == "application/problem+json"
    assert isinstance(body["detail"], str)
    assert isinstance(body["code"], str)
    assert body["type"].startswith("https://api.moneybeeloan.com/problems/")
    assert body["status"] == 404
    assert body["instance"]
    assert "context" not in body


def test_bucket_for_path_matches_public_and_webhook_prefixes():
    assert _bucket_for_path("/api/v2/public/contact-requests") == "public"
    assert _bucket_for_path("/api/v1/public/callback-requests") == "public"
    assert _bucket_for_path("/api/v2/webhooks/providers/plaid") == "webhook"
    assert _bucket_for_path("/api/v2/applications") is None


def test_rate_limit_blocks_after_configured_threshold():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def ok(request):
        return PlainTextResponse("ok")

    reset_rate_limit_state()
    inner = Starlette(routes=[Route("/api/v2/public/ping", ok)])
    limited = InMemoryRateLimitMiddleware(inner, limits_per_minute={"public": 2, "webhook": 2})

    with TestClient(limited) as client:
        first = client.get("/api/v2/public/ping")
        second = client.get("/api/v2/public/ping")
        third = client.get("/api/v2/public/ping")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["content-type"] == "application/problem+json"
    assert "Retry-After" in third.headers
    reset_rate_limit_state()
