"""
RulesService — stateless, synchronous rule-based fraud checks.

Each rule receives the transaction and returns a partial score contribution
plus an optional reason string.
"""

import logging

from app.config import settings
from app.models.transaction import TransactionRequest

logger = logging.getLogger(__name__)

# --- Score contributions per rule (Phase 2) ---
HIGH_AMOUNT_SCORE = 0.4
HIGH_RISK_COUNTRY_SCORE = 0.4
ROUND_AMOUNT_SCORE = 0.3
NEW_ACCOUNT_SCORE = 0.8
HIGH_RISK_MERCHANT_SCORE = 0.5
INTERNATIONAL_TRANSACTION_SCORE = 0.15
UNUSUAL_HOUR_SCORE = 0.15

# --- Round amount detection ---
ROUND_AMOUNT_MODULO = 100.0

# --- Unusual hour boundaries (UTC) ---
UNUSUAL_HOUR_START = 0
UNUSUAL_HOUR_END = 6


class RulesService:
    """Stateless, deterministic rule-based fraud scoring."""

    def evaluate(self, transaction: TransactionRequest) -> tuple[float, list[str]]:
        """Run all rule checks and return (capped_score, reasons)."""
        high_amount_score, high_amount_reason = self._check_high_amount(transaction)
        high_risk_country_score, high_risk_country_reason = self._check_high_risk_country(
            transaction
        )
        round_amount_score, round_amount_reason = self._check_round_amount(transaction)
        new_account_score, new_account_reason = self._check_new_account(transaction)
        high_risk_merchant_score, high_risk_merchant_reason = self._check_high_risk_merchant(
            transaction
        )
        international_score, international_reason = self._check_international_transaction(
            transaction,
            high_risk_country_triggered=high_risk_country_reason is not None,
        )
        unusual_hour_score, unusual_hour_reason = self._check_unusual_hour(transaction)

        checks = [
            (high_amount_score, high_amount_reason),
            (high_risk_country_score, high_risk_country_reason),
            (round_amount_score, round_amount_reason),
            (new_account_score, new_account_reason),
            (high_risk_merchant_score, high_risk_merchant_reason),
            (international_score, international_reason),
            (unusual_hour_score, unusual_hour_reason),
        ]

        total_score = 0.0
        reasons: list[str] = []

        for score, reason in checks:
            total_score += score
            if reason is not None:
                reasons.append(reason)

        has_critical_country_or_amount = (
            high_amount_reason is not None or high_risk_country_reason is not None
        )
        has_onboarding_pair = (
            new_account_reason is not None and high_risk_merchant_reason is not None
        )

        if has_onboarding_pair and not has_critical_country_or_amount:
            total_score = min(total_score, 0.70)

        return min(total_score, 1.0), reasons

    def _check_high_amount(
        self, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Flag transactions above the configured high-amount threshold."""
        if transaction.amount > settings.HIGH_AMOUNT_THRESHOLD:
            return HIGH_AMOUNT_SCORE, "high_amount"
        return 0.0, None

    def _check_high_risk_country(
        self, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Flag transactions originating from a high-risk country."""
        if transaction.country in settings.HIGH_RISK_COUNTRIES:
            return HIGH_RISK_COUNTRY_SCORE, "high_risk_country"
        return 0.0, None

    def _check_round_amount(
        self, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Flag suspiciously round/clean amounts (multiples of $100)."""
        if (
            0 < transaction.amount <= settings.HIGH_AMOUNT_THRESHOLD
            and transaction.amount % ROUND_AMOUNT_MODULO == 0
        ):
            return ROUND_AMOUNT_SCORE, "round_amount"
        return 0.0, None

    def _check_new_account(
        self, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Flag transactions from accounts younger than the configured threshold."""
        if (
            transaction.account_age_days is not None
            and transaction.account_age_days < settings.RULE_NEW_ACCOUNT_DAYS
        ):
            return NEW_ACCOUNT_SCORE, "new_account"
        return 0.0, None

    def _check_high_risk_merchant(
        self, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Flag transactions to merchants in high-risk categories."""
        if (
            transaction.merchant_category is not None
            and transaction.merchant_category.lower() in settings.HIGH_RISK_MERCHANTS
        ):
            return HIGH_RISK_MERCHANT_SCORE, "high_risk_merchant"
        return 0.0, None

    def _check_international_transaction(
        self,
        transaction: TransactionRequest,
        high_risk_country_triggered: bool = False,
    ) -> tuple[float, str | None]:
        """Flag cross-border transactions."""
        if transaction.is_international is True and not high_risk_country_triggered:
            return INTERNATIONAL_TRANSACTION_SCORE, "international_transaction"
        return 0.0, None

    def _check_unusual_hour(
        self, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Flag transactions occurring between midnight and 6 AM UTC."""
        hour = (
            transaction.transaction_hour
            if transaction.transaction_hour is not None
            else transaction.timestamp.hour
        )
        if UNUSUAL_HOUR_START <= hour < UNUSUAL_HOUR_END:
            return UNUSUAL_HOUR_SCORE, "unusual_hour"
        return 0.0, None
