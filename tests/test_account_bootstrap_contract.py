import pytest
from fastapi import HTTPException

from app.account_routes import BORROWER_PERMISSIONS, _claim_bool, _display_name
from app.config import settings
from app.request_context import enforce_portal_client


def test_email_verified_claim_is_fail_closed():
    assert _claim_bool(True) is True
    assert _claim_bool("true") is True
    assert _claim_bool("1") is True
    assert _claim_bool(False) is False
    assert _claim_bool("false") is False
    assert _claim_bool(None) is False


def test_display_name_uses_verified_profile_without_trusting_password_data():
    claims = {
        "given_name": "Jane",
        "family_name": "Borrower",
    }
    assert _display_name(claims, "jane@example.com") == "Jane Borrower"
    assert _display_name({}, "jane@example.com") == "jane"


def test_bootstrap_path_accepts_only_configured_borrower_client():
    borrower_client = sorted(settings.portal_client_ids["borrower"])[0]
    assert enforce_portal_client(
        "/api/v2/account/bootstrap",
        {"azp": borrower_client},
    ) == borrower_client

    admin_client = sorted(settings.portal_client_ids["admin"])[0]
    with pytest.raises(HTTPException) as caught:
        enforce_portal_client(
            "/api/v2/account/bootstrap",
            {"azp": admin_client},
        )
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "PORTAL_TOKEN_MISMATCH"


def test_bootstrap_role_is_least_privilege_borrower_scope():
    assert set(BORROWER_PERMISSIONS) == {
        "application.read.own",
        "application.edit.own",
        "application.submit.own",
        "condition.read.own",
        "complaint.create.own",
        "credit.authorize.own",
        "offer.accept.own",
    }
    assert "*" not in BORROWER_PERMISSIONS
    assert "funding.confirm" not in BORROWER_PERMISSIONS
