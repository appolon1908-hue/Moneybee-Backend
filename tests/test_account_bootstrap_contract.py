from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.account_routes import (
    BORROWER_PERMISSIONS,
    CANONICAL_ACCOUNT_PROVISIONED_EVENT,
    _claim_bool,
    _display_name,
    _require_active_borrower_membership,
    _require_active_borrower_role,
    _require_active_borrower_role_binding,
    _select_active_borrower_membership,
)
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


def test_bootstrap_rejects_suspended_borrower_membership():
    with pytest.raises(HTTPException) as caught:
        _require_active_borrower_membership(SimpleNamespace(active=False))

    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "MEMBERSHIP_INACTIVE"


def test_bootstrap_accepts_existing_active_borrower_membership():
    _require_active_borrower_membership(SimpleNamespace(active=True))


def test_bootstrap_preserves_globally_disabled_borrower_role():
    with pytest.raises(HTTPException) as caught:
        _require_active_borrower_role(SimpleNamespace(active=False))

    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "ROLE_INACTIVE"


def test_bootstrap_preserves_revoked_borrower_role_binding():
    with pytest.raises(HTTPException) as caught:
        _require_active_borrower_role_binding(SimpleNamespace(active=False))

    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "ROLE_BINDING_INACTIVE"


def test_bootstrap_requires_tenant_selection_when_borrower_memberships_are_ambiguous():
    memberships = [
        SimpleNamespace(active=True, organization_id="org-a"),
        SimpleNamespace(active=True, organization_id="org-b"),
    ]
    with pytest.raises(HTTPException) as caught:
        _select_active_borrower_membership(memberships)

    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "TENANT_SELECTION_REQUIRED"


def test_bootstrap_selects_only_active_borrower_membership():
    inactive = SimpleNamespace(active=False, organization_id="org-disabled")
    active = SimpleNamespace(active=True, organization_id="org-active")
    assert _select_active_borrower_membership([inactive, active]) is active


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


def test_bootstrap_emits_canonical_moneybee_account_event():
    assert CANONICAL_ACCOUNT_PROVISIONED_EVENT == "codestra.moneybee.account.provisioned"
