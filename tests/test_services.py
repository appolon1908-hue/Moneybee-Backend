import pytest

from app.services import ConflictError, transition_application


def test_valid_transition() -> None:
    assert transition_application("draft", "submitted") == "submitted"


def test_invalid_transition() -> None:
    with pytest.raises(ConflictError):
        transition_application("draft", "funded")
