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
NEW_ACCOUNT_SCORE = 0.25
HIGH_RISK_MERCHANT_SCORE = 0.2
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
        checks = [
            self._check_high_amount(transaction),
            self._check_high_risk_country(transaction),
            self._check_round_amount(transaction),
            self._check_new_account(transaction),
            self._check_high_risk_merchant(transaction),
            self._check_international_transaction(transaction),
            self._check_unusual_hour(transaction),
        ]

        total_score = 0.0
        reasons: list[str] = []

        for score, reason in checks:
            total_score += score
            if reason is not None:
                reasons.append(reason)

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
        if transaction.amount > 0 and transaction.amount % ROUND_AMOUNT_MODULO == 0:
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
        self, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Flag cross-border transactions."""
        if transaction.is_international is True:
            return INTERNATIONAL_TRANSACTION_SCORE, "international_transaction"
        return 0.0, None

    def _check_unusual_hour(
        self, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Flag transactions occurring between midnight and 6 AM UTC."""
        if UNUSUAL_HOUR_START <= transaction.timestamp.hour < UNUSUAL_HOUR_END:
            return UNUSUAL_HOUR_SCORE, "unusual_hour"
        return 0.0, None
