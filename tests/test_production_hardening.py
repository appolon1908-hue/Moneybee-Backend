import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.commands import parse_expected_version
from app.main import app


def test_expected_version_parser_accepts_http_etag_forms():
    assert parse_expected_version("17") == 17
    assert parse_expected_version('"18"') == 18
    assert parse_expected_version('W/"19"') == 19


def test_expected_version_parser_rejects_invalid_values():
    with pytest.raises(HTTPException) as caught:
        parse_expected_version("not-a-version")

    assert caught.value.status_code == 400
    assert caught.value.detail["code"] == "INVALID_EXPECTED_VERSION"


def test_readiness_report_refuses_to_claim_ready_without_evidence():
    with TestClient(app) as client:
        response = client.get("/api/v2/admin/system/readiness")
        exceptions = client.get("/api/v2/admin/operational-exceptions")

    assert response.status_code == 200
    report = response.json()
    assert report["FINAL_STATUS"] == "PARTIAL"
    assert report["SOURCE_SHA"] is None
    assert report["BLOCKERS"]
    assert report["NEXT_SAFE_ACTION"] in report["BLOCKERS"]
    assert exceptions.status_code == 200

