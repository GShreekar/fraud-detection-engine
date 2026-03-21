import pytest
from datetime import datetime

from app.models.transaction import TransactionRequest
from app.services.rules import (
    HIGH_AMOUNT_SCORE,
    HIGH_RISK_COUNTRY_SCORE,
    HIGH_RISK_MERCHANT_SCORE,
    INTERNATIONAL_TRANSACTION_SCORE,
    NEW_ACCOUNT_SCORE,
    ROUND_AMOUNT_SCORE,
    UNUSUAL_HOUR_SCORE,
    RulesService,
)


@pytest.fixture
def rules_service() -> RulesService:
    return RulesService()


# ── _check_high_amount ──────────────────────────────────────────────


def test_high_amount_rule_triggers(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 1500.0
    score, reason = rules_service._check_high_amount(clean_transaction)
    assert score == HIGH_AMOUNT_SCORE
    assert reason == "high_amount"


def test_high_amount_rule_does_not_trigger_below_threshold(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 999.99
    score, reason = rules_service._check_high_amount(clean_transaction)
    assert score == 0.0
    assert reason is None


def test_high_amount_rule_does_not_trigger_at_threshold(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 1000.0
    score, reason = rules_service._check_high_amount(clean_transaction)
    assert score == 0.0
    assert reason is None


# ── _check_high_risk_country ────────────────────────────────────────


def test_high_risk_country_rule_triggers(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.country = "NG"
    score, reason = rules_service._check_high_risk_country(clean_transaction)
    assert score == HIGH_RISK_COUNTRY_SCORE
    assert reason == "high_risk_country"


def test_high_risk_country_rule_does_not_trigger_safe_country(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.country = "US"
    score, reason = rules_service._check_high_risk_country(clean_transaction)
    assert score == 0.0
    assert reason is None


# ── _check_round_amount ────────────────────────────────────────────


def test_round_amount_rule_triggers_exact_1000(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 1000.0
    score, reason = rules_service._check_round_amount(clean_transaction)
    assert score == ROUND_AMOUNT_SCORE
    assert reason == "round_amount"


def test_round_amount_rule_triggers_exact_500(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 500.0
    score, reason = rules_service._check_round_amount(clean_transaction)
    assert score == ROUND_AMOUNT_SCORE
    assert reason == "round_amount"


def test_round_amount_rule_triggers_exact_100(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 100.0
    score, reason = rules_service._check_round_amount(clean_transaction)
    assert score == ROUND_AMOUNT_SCORE
    assert reason == "round_amount"


def test_round_amount_rule_does_not_trigger_non_round(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 499.99
    score, reason = rules_service._check_round_amount(clean_transaction)
    assert score == 0.0
    assert reason is None


# ── _check_new_account ─────────────────────────────────────────────


def test_new_account_rule_triggers_for_young_account(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.account_age_days = 5
    score, reason = rules_service._check_new_account(clean_transaction)
    assert score == NEW_ACCOUNT_SCORE
    assert reason == "new_account"


def test_new_account_rule_does_not_trigger_for_old_account(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.account_age_days = 365
    score, reason = rules_service._check_new_account(clean_transaction)
    assert score == 0.0
    assert reason is None


def test_new_account_rule_does_not_trigger_when_missing(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    # account_age_days defaults to None
    score, reason = rules_service._check_new_account(clean_transaction)
    assert score == 0.0
    assert reason is None


def test_new_account_rule_does_not_trigger_at_threshold(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.account_age_days = 30  # exactly at threshold
    score, reason = rules_service._check_new_account(clean_transaction)
    assert score == 0.0
    assert reason is None


# ── _check_high_risk_merchant ──────────────────────────────────────


def test_high_risk_merchant_rule_triggers(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.merchant_category = "crypto"
    score, reason = rules_service._check_high_risk_merchant(clean_transaction)
    assert score == HIGH_RISK_MERCHANT_SCORE
    assert reason == "high_risk_merchant"


def test_high_risk_merchant_rule_triggers_case_insensitive(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.merchant_category = "GAMBLING"
    score, reason = rules_service._check_high_risk_merchant(clean_transaction)
    assert score == HIGH_RISK_MERCHANT_SCORE
    assert reason == "high_risk_merchant"


def test_high_risk_merchant_rule_does_not_trigger_safe_category(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.merchant_category = "electronics"
    score, reason = rules_service._check_high_risk_merchant(clean_transaction)
    assert score == 0.0
    assert reason is None


def test_high_risk_merchant_rule_does_not_trigger_when_missing(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    # merchant_category defaults to None
    score, reason = rules_service._check_high_risk_merchant(clean_transaction)
    assert score == 0.0
    assert reason is None


# ── _check_unusual_hour ────────────────────────────────────────────


def test_unusual_hour_rule_triggers_at_3am(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.timestamp = datetime(2026, 1, 1, 3, 0, 0)
    score, reason = rules_service._check_unusual_hour(clean_transaction)
    assert score == UNUSUAL_HOUR_SCORE
    assert reason == "unusual_hour"


def test_unusual_hour_rule_triggers_at_midnight(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.timestamp = datetime(2026, 1, 1, 0, 0, 0)
    score, reason = rules_service._check_unusual_hour(clean_transaction)
    assert score == UNUSUAL_HOUR_SCORE
    assert reason == "unusual_hour"


def test_unusual_hour_rule_does_not_trigger_at_6am(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.timestamp = datetime(2026, 1, 1, 6, 0, 0)
    score, reason = rules_service._check_unusual_hour(clean_transaction)
    assert score == 0.0
    assert reason is None


def test_unusual_hour_rule_does_not_trigger_at_noon(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.timestamp = datetime(2026, 1, 1, 12, 0, 0)
    score, reason = rules_service._check_unusual_hour(clean_transaction)
    assert score == 0.0
    assert reason is None


def test_unusual_hour_rule_uses_transaction_hour_when_present(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    """Explicit transaction_hour should override timestamp hour for checks."""
    clean_transaction.timestamp = datetime(2026, 1, 1, 12, 0, 0)
    clean_transaction.transaction_hour = 2
    score, reason = rules_service._check_unusual_hour(clean_transaction)
    assert score == UNUSUAL_HOUR_SCORE
    assert reason == "unusual_hour"


# ── evaluate() ──────────────────────────────────────────────────────


def test_evaluate_returns_zero_for_clean_transaction(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 99.50  # avoid multiples of 100
    clean_transaction.timestamp = datetime(2026, 1, 1, 12, 0, 0)  # noon
    score, reasons = rules_service.evaluate(clean_transaction)
    assert score == 0.0
    assert reasons == []


def test_evaluate_returns_correct_score_for_multiple_rules(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    # Use a non-round amount so only high_amount + high_risk_country trigger
    clean_transaction.amount = 1500.50
    clean_transaction.country = "NG"
    clean_transaction.timestamp = datetime(2026, 1, 1, 12, 0, 0)  # noon
    score, reasons = rules_service.evaluate(clean_transaction)
    expected = HIGH_AMOUNT_SCORE + HIGH_RISK_COUNTRY_SCORE
    assert score == pytest.approx(expected)
    assert "high_amount" in reasons
    assert "high_risk_country" in reasons


def test_evaluate_caps_score_at_one(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    # Trigger many rules: high amount + high-risk country + round amount + unusual hour
    clean_transaction.amount = 1500.0
    clean_transaction.country = "NG"
    clean_transaction.timestamp = datetime(2026, 1, 1, 3, 0, 0)  # 3 AM
    score, reasons = rules_service.evaluate(clean_transaction)
    assert score <= 1.0
    assert len(reasons) >= 3


def test_evaluate_returns_all_reasons_when_all_rules_trigger(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 1500.0
    clean_transaction.country = "KP"
    clean_transaction.account_age_days = 5
    clean_transaction.merchant_category = "crypto"
    clean_transaction.timestamp = datetime(2026, 1, 1, 3, 0, 0)  # 3 AM
    score, reasons = rules_service.evaluate(clean_transaction)
    assert "high_amount" in reasons
    assert "high_risk_country" in reasons
    assert "new_account" in reasons
    assert "high_risk_merchant" in reasons
    assert "international_transaction" not in reasons
    assert "unusual_hour" in reasons
    assert score == 1.0  # capped
