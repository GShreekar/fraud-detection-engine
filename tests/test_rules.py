import pytest

from app.models.transaction import TransactionRequest
from app.services.rules import (
    HIGH_AMOUNT_SCORE,
    HIGH_RISK_COUNTRY_SCORE,
    ROUND_AMOUNT_SCORE,
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


def test_round_amount_rule_does_not_trigger_non_round(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 499.99
    score, reason = rules_service._check_round_amount(clean_transaction)
    assert score == 0.0
    assert reason is None


# ── evaluate() ──────────────────────────────────────────────────────


def test_evaluate_returns_zero_for_clean_transaction(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    score, reasons = rules_service.evaluate(clean_transaction)
    assert score == 0.0
    assert reasons == []


def test_evaluate_returns_correct_score_for_multiple_rules(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    # Use a non-round amount so only high_amount + high_risk_country trigger
    clean_transaction.amount = 1500.50
    clean_transaction.country = "NG"
    score, reasons = rules_service.evaluate(clean_transaction)
    expected = HIGH_AMOUNT_SCORE + HIGH_RISK_COUNTRY_SCORE
    assert score == pytest.approx(expected)
    assert "high_amount" in reasons
    assert "high_risk_country" in reasons


def test_evaluate_caps_score_at_one(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    # Trigger all three rules: high amount + high-risk country + round amount
    clean_transaction.amount = 1500.0
    clean_transaction.country = "NG"
    # 1500.0 is a multiple of 500 => round_amount also triggers
    score, reasons = rules_service.evaluate(clean_transaction)
    assert score <= 1.0
    assert len(reasons) == 3


def test_evaluate_returns_all_reasons_when_all_rules_trigger(
    rules_service: RulesService, clean_transaction: TransactionRequest
) -> None:
    clean_transaction.amount = 1500.0
    clean_transaction.country = "KP"
    score, reasons = rules_service.evaluate(clean_transaction)
    assert "high_amount" in reasons
    assert "high_risk_country" in reasons
    assert "round_amount" in reasons
