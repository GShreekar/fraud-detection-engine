"""
tests/test_models.py — Unit tests for Pydantic model validation.
"""

import pytest
from pydantic import ValidationError

from app.models.transaction import FraudDecision, FraudScoreResponse, TransactionRequest


# ── TransactionRequest — valid construction ────────────────────────


def test_valid_transaction_creates_successfully() -> None:
    """A fully valid payload should instantiate without errors."""
    txn = TransactionRequest(
        transaction_id="txn_001",
        user_id="user_1",
        amount=250.0,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address="10.0.0.1",
        country="US",
    )
    assert txn.transaction_id == "txn_001"
    assert txn.amount == 250.0


def test_timestamp_defaults_to_utcnow() -> None:
    """When timestamp is omitted, it should default to the current UTC time."""
    txn = TransactionRequest(
        transaction_id="txn_ts",
        user_id="user_1",
        amount=100.0,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address="10.0.0.1",
        country="US",
    )
    assert txn.timestamp is not None


# ── TransactionRequest — missing required fields ──────────────────


def test_missing_transaction_id_raises_validation_error() -> None:
    """Omitting transaction_id should raise a ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionRequest(
            user_id="user_1",
            amount=100.0,
            merchant_id="merchant_1",
            device_id="device_abc",
            ip_address="10.0.0.1",
            country="US",
        )
    assert "transaction_id" in str(exc_info.value)


def test_missing_user_id_raises_validation_error() -> None:
    """Omitting user_id should raise a ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionRequest(
            transaction_id="txn_001",
            amount=100.0,
            merchant_id="merchant_1",
            device_id="device_abc",
            ip_address="10.0.0.1",
            country="US",
        )
    assert "user_id" in str(exc_info.value)


def test_missing_amount_raises_validation_error() -> None:
    """Omitting amount should raise a ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionRequest(
            transaction_id="txn_001",
            user_id="user_1",
            merchant_id="merchant_1",
            device_id="device_abc",
            ip_address="10.0.0.1",
            country="US",
        )
    assert "amount" in str(exc_info.value)


def test_missing_multiple_fields_raises_validation_error() -> None:
    """Omitting multiple required fields should raise errors for each."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionRequest(
            amount=100.0,
            country="US",
        )
    errors = exc_info.value.errors()
    missing_fields = {e["loc"][0] for e in errors}
    assert "transaction_id" in missing_fields
    assert "user_id" in missing_fields
    assert "merchant_id" in missing_fields


# ── TransactionRequest — boundary values ──────────────────────────


def test_amount_must_be_greater_than_zero() -> None:
    """An amount of 0 should fail validation (gt=0 constraint)."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionRequest(
            transaction_id="txn_001",
            user_id="user_1",
            amount=0.0,
            merchant_id="merchant_1",
            device_id="device_abc",
            ip_address="10.0.0.1",
            country="US",
        )
    assert "amount" in str(exc_info.value)


def test_negative_amount_fails_validation() -> None:
    """A negative amount should fail validation."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionRequest(
            transaction_id="txn_001",
            user_id="user_1",
            amount=-50.0,
            merchant_id="merchant_1",
            device_id="device_abc",
            ip_address="10.0.0.1",
            country="US",
        )
    assert "amount" in str(exc_info.value)


def test_very_small_positive_amount_is_valid() -> None:
    """A very small positive amount should be accepted."""
    txn = TransactionRequest(
        transaction_id="txn_small",
        user_id="user_1",
        amount=0.01,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address="10.0.0.1",
        country="US",
    )
    assert txn.amount == 0.01


def test_country_too_short_fails_validation() -> None:
    """A single-character country code should fail (min_length=2)."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionRequest(
            transaction_id="txn_001",
            user_id="user_1",
            amount=100.0,
            merchant_id="merchant_1",
            device_id="device_abc",
            ip_address="10.0.0.1",
            country="U",
        )
    assert "country" in str(exc_info.value)


def test_country_too_long_fails_validation() -> None:
    """A three-character country code should fail (max_length=2)."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionRequest(
            transaction_id="txn_001",
            user_id="user_1",
            amount=100.0,
            merchant_id="merchant_1",
            device_id="device_abc",
            ip_address="10.0.0.1",
            country="USA",
        )
    assert "country" in str(exc_info.value)


def test_country_exactly_two_chars_is_valid() -> None:
    """A two-character country code should be accepted."""
    txn = TransactionRequest(
        transaction_id="txn_cc",
        user_id="user_1",
        amount=100.0,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address="10.0.0.1",
        country="GB",
    )
    assert txn.country == "GB"


# ── FraudScoreResponse — validation ──────────────────────────────


def test_fraud_score_below_zero_fails_validation() -> None:
    """A fraud_score below 0.0 should fail (ge=0.0 constraint)."""
    with pytest.raises(ValidationError):
        FraudScoreResponse(
            transaction_id="txn_001",
            fraud_score=-0.1,
            decision=FraudDecision.ALLOW,
            reasons=[],
        )


def test_fraud_score_above_one_fails_validation() -> None:
    """A fraud_score above 1.0 should fail (le=1.0 constraint)."""
    with pytest.raises(ValidationError):
        FraudScoreResponse(
            transaction_id="txn_001",
            fraud_score=1.1,
            decision=FraudDecision.BLOCK,
            reasons=[],
        )


def test_fraud_score_at_boundaries_is_valid() -> None:
    """Scores of exactly 0.0 and 1.0 should be accepted."""
    low = FraudScoreResponse(
        transaction_id="txn_low",
        fraud_score=0.0,
        decision=FraudDecision.ALLOW,
        reasons=[],
    )
    high = FraudScoreResponse(
        transaction_id="txn_high",
        fraud_score=1.0,
        decision=FraudDecision.BLOCK,
        reasons=["high_amount"],
    )
    assert low.fraud_score == 0.0
    assert high.fraud_score == 1.0


# ── FraudDecision enum ────────────────────────────────────────────


def test_fraud_decision_values() -> None:
    """FraudDecision should have exactly three members."""
    assert set(FraudDecision) == {
        FraudDecision.ALLOW,
        FraudDecision.REVIEW,
        FraudDecision.BLOCK,
    }


def test_fraud_decision_is_string_enum() -> None:
    """FraudDecision values should be usable as strings."""
    assert FraudDecision.ALLOW == "ALLOW"
    assert FraudDecision.REVIEW == "REVIEW"
    assert FraudDecision.BLOCK == "BLOCK"
