import pytest
from fastapi import HTTPException

from app.portal_clients import (
    enforce_portal_client,
    portal_client_ids,
    self_registration_client_ids,
)


@pytest.fixture(autouse=True)
def distinct_clients(monkeypatch):
    monkeypatch.setenv("BORROWER_OIDC_CLIENT_IDS", "moneybee-borrower")
    monkeypatch.setenv("LENDER_OIDC_CLIENT_IDS", "moneybee-lender")
    monkeypatch.setenv("ADMIN_OIDC_CLIENT_IDS", "moneybee-admin")
    monkeypatch.setenv("ACCOUNT_SELF_REGISTRATION_CLIENT_IDS", "moneybee-borrower")


@pytest.mark.parametrize(
    ("path", "client_id"),
    [
        ("/api/v2/auth/bootstrap", "moneybee-borrower"),
        ("/api/v1/auth/bootstrap", "moneybee-borrower"),
        ("/api/v2/borrower/overview", "moneybee-borrower"),
        ("/api/v1/borrower/overview", "moneybee-borrower"),
        ("/api/v2/lender/dashboard", "moneybee-lender"),
        ("/api/v1/lender/dashboard", "moneybee-lender"),
        ("/api/v2/lenders/00000000-0000-0000-0000-000000000000/programs", "moneybee-lender"),
        ("/api/v1/lenders/00000000-0000-0000-0000-000000000000/programs", "moneybee-lender"),
        ("/api/v2/admin/overview", "moneybee-admin"),
        ("/api/v1/admin/overview", "moneybee-admin"),
        ("/api/v2/applications", "moneybee-borrower"),
        ("/api/v1/applications", "moneybee-borrower"),
        ("/api/v2/applications", "moneybee-admin"),
        ("/api/v1/applications", "moneybee-admin"),
        ("/api/v2/offers/00000000-0000-0000-0000-000000000000/accept", "moneybee-borrower"),
        ("/api/v1/offers/00000000-0000-0000-0000-000000000000/accept", "moneybee-borrower"),
    ],
)
def test_correct_portal_token_is_accepted(path: str, client_id: str):
    assert enforce_portal_client(path, {"azp": client_id}) == client_id


@pytest.mark.parametrize(
    ("path", "client_id"),
    [
        ("/api/v2/borrower/overview", "moneybee-lender"),
        ("/api/v1/borrower/overview", "moneybee-lender"),
        ("/api/v2/lender/dashboard", "moneybee-borrower"),
        ("/api/v1/lender/dashboard", "moneybee-borrower"),
        ("/api/v2/admin/overview", "moneybee-borrower"),
        ("/api/v1/admin/overview", "moneybee-borrower"),
        ("/api/v2/applications", "moneybee-lender"),
        ("/api/v1/applications", "moneybee-lender"),
        ("/api/v2/auth/bootstrap", "moneybee-admin"),
        ("/api/v1/auth/bootstrap", "moneybee-admin"),
    ],
)
def test_cross_portal_token_is_rejected(path: str, client_id: str):
    with pytest.raises(HTTPException) as caught:
        enforce_portal_client(path, {"azp": client_id})
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "PORTAL_TOKEN_MISMATCH"


def test_portal_client_ids_must_be_distinct(monkeypatch):
    monkeypatch.setenv("ADMIN_OIDC_CLIENT_IDS", "moneybee-borrower")
    with pytest.raises(HTTPException) as caught:
        portal_client_ids()
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "PORTAL_CLIENT_CONFIGURATION_INVALID"


def test_self_registration_must_be_borrower_only(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SELF_REGISTRATION_CLIENT_IDS", "moneybee-lender")
    with pytest.raises(HTTPException) as caught:
        self_registration_client_ids()
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "PORTAL_CLIENT_CONFIGURATION_INVALID"
