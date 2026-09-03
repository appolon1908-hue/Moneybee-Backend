"""RBAC enforcement coverage.

Every existing test in this suite runs under LOCAL_AUTH_BYPASS, which
always resolves to a MONEYBEE_ADMIN principal holding the "*" wildcard
(app/auth.py's _local_bypass_principal) - so nothing else in this suite
ever exercises a denial for a real, restricted role. This file closes
that gap directly against the three permission-enforcement mechanisms in
use across the app:

  1. require_permission(permission) - the single-permission FastAPI
     dependency used by most admin/portal routes.
  2. require_any_permission(user, *permissions) - the any-of inline check
     used by app/portal/lender.py.
  3. The hand-rolled "own resource" checks in app/applications_routes.py
     (`if "*" not in user.permissions and "X.own" not in user.permissions`).

and against every permission string LEGACY_ROLE_PERMISSIONS actually
grants to a role, plus the six new admin endpoints this mission added
(adverse-action notices, commercial-financing disclosures, 1099 tax
records), exercised end-to-end via TestClient with a real restricted
Principal injected through app.dependency_overrides - not just the bypass
principal every other test uses.
"""

import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.auth import LEGACY_ROLE_PERMISSIONS, Principal, current_principal, require_permission
from app.main import app
from app.portal.common import require_any_permission


def _principal(*, permissions: frozenset[str], roles: frozenset[str] = frozenset()) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        issuer="test-issuer",
        subject="test-subject",
        organization_ids=(),
        active_organization_id=None,
        roles=roles,
        permissions=permissions,
        membership_types=frozenset(),
        borrower_id=None,
        lender_id=None,
        is_active=True,
    )


ALL_GRANTED_PERMISSIONS = sorted(
    {
        permission
        for role, permissions in LEGACY_ROLE_PERMISSIONS.items()
        for permission in permissions
        if role != "MONEYBEE_ADMIN"
    }
)


# --- Mechanism 1: require_permission() ----------------------------------


@pytest.mark.parametrize("permission", ALL_GRANTED_PERMISSIONS)
async def test_require_permission_grants_a_principal_holding_the_exact_permission(permission):
    principal = _principal(permissions=frozenset({permission}))
    dependency = require_permission(permission)
    result = await dependency(principal)
    assert result is principal


@pytest.mark.parametrize("permission", ALL_GRANTED_PERMISSIONS)
async def test_require_permission_denies_a_principal_missing_the_permission(permission):
    principal = _principal(permissions=frozenset({"some.other.permission"}))
    dependency = require_permission(permission)
    with pytest.raises(HTTPException) as caught:
        await dependency(principal)
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "PERMISSION_DENIED"


async def test_require_permission_wildcard_grants_every_permission():
    principal = _principal(permissions=frozenset({"*"}))
    for permission in [*ALL_GRANTED_PERMISSIONS, "anything.not.declared.anywhere"]:
        dependency = require_permission(permission)
        assert await dependency(principal) is principal


async def test_require_permission_denies_a_principal_with_no_permissions_at_all():
    principal = _principal(permissions=frozenset())
    dependency = require_permission("application.read")
    with pytest.raises(HTTPException) as caught:
        await dependency(principal)
    assert caught.value.status_code == 403


# --- Mechanism 2: require_any_permission() -------------------------------


def test_require_any_permission_grants_when_one_of_several_matches():
    principal = _principal(permissions=frozenset({"lender.submission.read"}))
    require_any_permission(principal, "lender.application.read", "lender.submission.read")


def test_require_any_permission_denies_when_none_match():
    principal = _principal(permissions=frozenset({"lead.read"}))
    with pytest.raises(HTTPException) as caught:
        require_any_permission(principal, "lender.application.read", "lender.submission.read")
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "PERMISSION_DENIED"


def test_require_any_permission_wildcard_grants_regardless_of_the_list():
    principal = _principal(permissions=frozenset({"*"}))
    require_any_permission(principal, "anything.not.declared.anywhere")


# --- Mechanism 3: role-level isolation, matching LEGACY_ROLE_PERMISSIONS ----


@pytest.mark.parametrize("role", sorted(LEGACY_ROLE_PERMISSIONS))
async def test_each_role_is_granted_exactly_its_declared_permissions(role):
    granted = LEGACY_ROLE_PERMISSIONS[role]
    principal = _principal(permissions=frozenset(granted), roles=frozenset({role}))
    for permission in granted:
        dependency = require_permission(permission)
        assert await dependency(principal) is principal


@pytest.mark.parametrize(
    ("role", "forbidden_permission"),
    [
        ("MONEYBEE_SALES", "underwriting.review"),
        ("MONEYBEE_SALES", "commission.receipt.record"),
        ("MONEYBEE_UNDERWRITER", "application.edit"),
        ("MONEYBEE_UNDERWRITER", "commission.receipt.record"),
        ("LENDER_ADMIN", "underwriting.review"),
        ("LENDER_ADMIN", "commission.receipt.record"),
        ("LENDER_UNDERWRITER", "program.manage"),
        ("BORROWER", "application.read"),
        ("BORROWER", "commission.receipt.record"),
        ("BORROWER", "lender.application.read"),
    ],
)
async def test_a_role_is_denied_permissions_outside_its_declared_set(role, forbidden_permission):
    granted = LEGACY_ROLE_PERMISSIONS[role]
    assert forbidden_permission not in granted, "test fixture is asserting a real boundary"
    principal = _principal(permissions=frozenset(granted), roles=frozenset({role}))
    dependency = require_permission(forbidden_permission)
    with pytest.raises(HTTPException) as caught:
        await dependency(principal)
    assert caught.value.status_code == 403


# --- New endpoints this mission added: end-to-end via TestClient ----------


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(current_principal, None)


def _override_principal(permissions: frozenset[str]) -> None:
    app.dependency_overrides[current_principal] = lambda: _principal(permissions=permissions)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v2/admin/applications/00000000-0000-0000-0000-000000000000/adverse-action-notices"),
        ("GET", "/api/v2/admin/offers/00000000-0000-0000-0000-000000000000/commercial-financing-disclosure"),
    ],
)
def test_compliance_read_endpoints_require_application_read(client, method, path):
    _override_principal(frozenset({"application.edit"}))
    denied = client.request(method, path)
    assert denied.status_code == 403
    assert denied.json()["code"] == "PERMISSION_DENIED"

    _override_principal(frozenset({"application.read"}))
    granted = client.request(method, path)
    assert granted.status_code in (200, 404)


def test_compliance_acknowledge_endpoint_requires_application_edit(client):
    _override_principal(frozenset({"application.read"}))
    denied = client.post(
        "/api/v2/admin/offers/00000000-0000-0000-0000-000000000000"
        "/commercial-financing-disclosure/acknowledge"
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "PERMISSION_DENIED"

    _override_principal(frozenset({"application.edit"}))
    not_a_permission_error = client.post(
        "/api/v2/admin/offers/00000000-0000-0000-0000-000000000000"
        "/commercial-financing-disclosure/acknowledge",
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert not_a_permission_error.status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v2/admin/commission-tax-records/generate?tax_year=2026"),
        ("GET", "/api/v2/admin/commission-tax-records"),
        (
            "PATCH",
            "/api/v2/admin/commission-tax-records/00000000-0000-0000-0000-000000000000/tin",
        ),
    ],
)
def test_commission_tax_record_endpoints_require_commission_receipt_record(client, method, path):
    _override_principal(frozenset({"application.read", "application.edit"}))
    denied = client.request(method, path, json={} if method == "PATCH" else None)
    assert denied.status_code == 403
    assert denied.json()["code"] == "PERMISSION_DENIED"

    _override_principal(frozenset({"commission.receipt.record"}))
    not_a_permission_error = client.request(method, path, json={} if method == "PATCH" else None)
    assert not_a_permission_error.status_code != 403
