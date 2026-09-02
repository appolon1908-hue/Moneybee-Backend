import pytest
from pydantic import ValidationError

from app.compliance_schemas import (
    CommissionTaxRecordFilingInput,
    CommissionTaxRecordTinInput,
)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            CommissionTaxRecordTinInput,
            {
                "recipient_name": "Casey Broker",
                "tin": "12-3456789",
                "acknowledged_by": "spoofed-actor",
            },
        ),
        (
            CommissionTaxRecordFilingInput,
            {
                "filing_reference": "IRS-TEST-1",
                "filed_by": "spoofed-actor",
            },
        ),
    ],
)
def test_compliance_commands_reject_unknown_fields(model, payload):
    with pytest.raises(ValidationError) as caught:
        model.model_validate(payload)
    assert "extra_forbidden" in str(caught.value)
