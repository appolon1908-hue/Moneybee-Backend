import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import Settings
from app.request_context import enforce_portal_client


@pytest.mark.parametrize(
    ("path", "client_id"),
    [
        ("/api/v2/borrower/overview", "moneybee-borrower"),
        ("/api/v2/applications", "moneybee-borrower"),
        ("/api/v2/offers/00000000-0000-0000-0000-000000000000/accept", "moneybee-borrower"),
        ("/api/v2/offers/00000000-0000-0000-0000-000000000000/commercial-financing-disclosure", "moneybee-borrower"),
        ("/api/v2/offers/00000000-0000-0000-0000-000000000000/commercial-financing-disclosure/acknowledge", "moneybee-borrower"),
        ("/api/v1/offers/00000000-0000-0000-0000-000000000000/commercial-financing-disclosure", "moneybee-borrower"),
        ("/api/v2/lender/dashboard", "moneybee-lender"),
        ("/api/v2/lenders/00000000-0000-0000-0000-000000000000/programs", "moneybee-lender"),
        ("/api/v2/admin/overview", "moneybee-admin"),
        ("/api/v2/finance/accounts", "moneybee-admin"),
        ("/api/v2/applications", "moneybee-admin"),
    ],
)
def test_correct_portal_token_is_accepted(path: str, client_id: str):
    assert enforce_portal_client(path, {"azp": client_id}) == client_id


@pytest.mark.parametrize(
    ("path", "client_id"),
    [
        ("/api/v2/borrower/overview", "moneybee-lender"),
        ("/api/v2/borrower/overview", "moneybee-admin"),
        ("/api/v2/lender/dashboard", "moneybee-borrower"),
        ("/api/v2/lender/dashboard", "moneybee-admin"),
        ("/api/v2/admin/overview", "moneybee-borrower"),
        ("/api/v2/admin/overview", "moneybee-lender"),
        ("/api/v2/finance/accounts", "moneybee-borrower"),
        ("/api/v2/finance/accounts", "moneybee-lender"),
        ("/api/v2/applications", "moneybee-lender"),
        ("/api/v2/offers/00000000-0000-0000-0000-000000000000/commercial-financing-disclosure", "moneybee-admin"),
        ("/api/v2/offers/00000000-0000-0000-0000-000000000000/commercial-financing-disclosure/acknowledge", "moneybee-lender"),
        ("/api/v1/offers/00000000-0000-0000-0000-000000000000/commercial-financing-disclosure", "moneybee-admin"),
    ],
)
def test_cross_portal_token_is_rejected(path: str, client_id: str):
    with pytest.raises(HTTPException) as caught:
        enforce_portal_client(path, {"azp": client_id})
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "PORTAL_TOKEN_MISMATCH"


def test_missing_authorized_party_is_rejected_for_portal_route():
    with pytest.raises(HTTPException) as caught:
        enforce_portal_client("/api/v2/finance/accounts", {})
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "PORTAL_TOKEN_MISMATCH"


def test_portal_client_configuration_must_be_nonempty_and_disjoint():
    with pytest.raises(ValidationError):
        Settings(
            borrower_oidc_client_ids_csv="moneybee-web",
            lender_oidc_client_ids_csv="moneybee-web",
            admin_oidc_client_ids_csv="moneybee-admin",
        )

    with pytest.raises(ValidationError):
        Settings(
            borrower_oidc_client_ids_csv="",
            lender_oidc_client_ids_csv="moneybee-lender",
            admin_oidc_client_ids_csv="moneybee-admin",
        )
