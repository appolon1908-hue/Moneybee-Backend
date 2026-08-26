import pytest
from fastapi import HTTPException

from app.lender_portal_routes import (
    LenderDecisionCreate,
    _canonical_hash,
    _expected_version,
)


def test_decision_request_hash_is_canonical() -> None:
    first = LenderDecisionCreate(
        decision="REQUEST_INFORMATION",
        notes="Need updated statements",
        requested_items=["January statement", "February statement"],
    )
    second = LenderDecisionCreate.model_validate(first.model_dump())
    assert _canonical_hash(first) == _canonical_hash(second)


def test_different_decision_payloads_have_different_hashes() -> None:
    approve = LenderDecisionCreate(decision="APPROVE", offer_amount="50000")
    decline = LenderDecisionCreate(decision="DECLINE")
    assert _canonical_hash(approve) != _canonical_hash(decline)


def test_if_match_requires_positive_integer_version() -> None:
    assert _expected_version('W/"7"') == 7
    assert _expected_version('"3"') == 3
    with pytest.raises(HTTPException) as missing:
        _expected_version(None)
    assert missing.value.status_code == 428
    with pytest.raises(HTTPException) as invalid:
        _expected_version("abc")
    assert invalid.value.status_code == 400
