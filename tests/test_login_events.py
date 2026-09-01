"""GET /me/sessions - the spec lists "login events" under Security, and
GET /me/sessions under the public/identity API contract target, but
nothing ever wrote a LoginEvent (the table didn't exist). GET
/auth/context is the endpoint a frontend calls once per session bootstrap
(right after it has a token), not the current_principal dependency every
request goes through - that's the signal used here, deduplicated so
repeated calls within a session don't produce a login event per call.
"""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi.testclient import TestClient

from app.main import app


def test_auth_context_records_a_login_event_visible_at_me_sessions():
    with TestClient(app) as client:
        context = client.get("/api/v2/auth/context")
        assert context.status_code == 200

        sessions = client.get("/api/v2/me/sessions")
        assert sessions.status_code == 200
        body = sessions.json()
        assert len(body) >= 1
        latest = body[0]
        assert latest["issuer"] == "local-bypass"
        assert "user_agent" in latest
        assert "subject" not in latest


def test_repeated_auth_context_calls_do_not_duplicate_the_login_event():
    with TestClient(app) as client:
        client.get("/api/v2/auth/context")
        client.get("/api/v2/auth/context")
        client.get("/api/v2/auth/context")

        sessions = client.get("/api/v2/me/sessions").json()
        # All three calls are the same bypass principal within the
        # dedup window - exactly one login event, not three.
        assert len(sessions) == 1


def test_me_sessions_returns_a_list_without_a_prior_login_error():
    # Not asserting an empty list: LOCAL_AUTH_BYPASS always resolves to the
    # same fixed "local-admin" principal, so another test in this same run
    # may have already recorded a login for it within the dedup window -
    # this only proves the endpoint itself never errors when called cold.
    with TestClient(app) as client:
        sessions = client.get("/api/v2/me/sessions")
        assert sessions.status_code == 200
        assert isinstance(sessions.json(), list)
