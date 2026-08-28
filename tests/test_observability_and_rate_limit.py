import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import app
from app.rate_limit import InMemoryRateLimitMiddleware, _bucket_for_path


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
