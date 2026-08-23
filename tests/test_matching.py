from decimal import Decimal
from types import SimpleNamespace

from app.services import score


def test_matching_returns_explainable_reasons():
    application = SimpleNamespace(
        requested_amount=Decimal("75000"),
        monthly_revenue=Decimal("85000"),
        time_in_business_months=36,
        state="FL",
        industry="TRUCKING",
    )
    program = SimpleNamespace(
        min_amount=Decimal("25000"),
        max_amount=Decimal("500000"),
        minimum_monthly_revenue=Decimal("50000"),
        minimum_time_in_business_months=24,
        states=["FL", "TX"],
        excluded_industries=["GAMBLING"],
    )
    eligible, value, reasons = score(application, program)
    assert eligible is True
    assert value == 100
    assert reasons == []
