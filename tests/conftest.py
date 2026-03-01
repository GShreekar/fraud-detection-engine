import pytest

from app.models.transaction import TransactionRequest


@pytest.fixture
def clean_transaction() -> TransactionRequest:
    """Default clean transaction that should not trigger any rule."""
    return TransactionRequest(
        transaction_id="txn_clean_001",
        user_id="user_1",
        amount=100.0,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address="10.0.0.1",
        country="US",
    )
