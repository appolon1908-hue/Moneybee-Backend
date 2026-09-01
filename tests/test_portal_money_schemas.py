from decimal import Decimal

from app.portal.schemas import BankTransactionRead, LenderProgramUpdate


def test_lender_program_money_fields_never_cross_a_float_boundary():
    payload = LenderProgramUpdate.model_validate(
        {
            "version": 1,
            "min_amount": "0.10",
            "max_amount": "125000.99",
            "minimum_monthly_revenue": "10000.25",
        }
    )

    assert payload.min_amount == Decimal("0.10")
    assert payload.max_amount == Decimal("125000.99")
    assert payload.minimum_monthly_revenue == Decimal("10000.25")
    assert isinstance(payload.min_amount, Decimal)
    assert isinstance(payload.max_amount, Decimal)
    assert isinstance(payload.minimum_monthly_revenue, Decimal)


def test_bank_transaction_response_preserves_decimal_amount():
    transaction = BankTransactionRead.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "account_id": None,
            "posted_at": "2026-09-01T00:00:00Z",
            "authorized_at": None,
            "name": "Exact decimal transaction",
            "merchant_name": None,
            "amount": "0.10",
            "currency": "USD",
            "pending": False,
            "removed": False,
            "categories": [],
        }
    )

    assert transaction.amount == Decimal("0.10")
    assert isinstance(transaction.amount, Decimal)
    assert transaction.model_dump(mode="json")["amount"] == "0.10"
