from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.admin_portal import _has_global_scope, _require_admin, _task_read


def test_moneybee_membership_is_required():
    principal = SimpleNamespace(
        membership_types={"BORROWER"},
        active_organization_id=uuid4(),
    )
    with pytest.raises(Exception) as exc_info:
        _require_admin(principal)
    assert getattr(exc_info.value, "status_code", None) == 403


def test_global_scope_requires_explicit_capability():
    restricted = SimpleNamespace(permissions={"lead.read"})
    privileged = SimpleNamespace(permissions={"lead.read", "capability.manage"})
    assert _has_global_scope(restricted) is False
    assert _has_global_scope(privileged) is True


def test_task_projection_is_allowlisted():
    task = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        title="Review lender decision",
        status="OPEN",
        priority="HIGH",
        metadata_payload={"decision_id": str(uuid4())},
        borrower_ssn="never-return-this",
        bank_account_number="never-return-this",
    )
    result = _task_read(task)
    assert result["title"] == "Review lender decision"
    assert "borrower_ssn" not in result
    assert "bank_account_number" not in result
