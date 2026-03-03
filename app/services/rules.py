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

# --- Round amount detection ---
ROUND_AMOUNT_MODULO = 500.0


class RulesService:
    """Stateless, deterministic rule-based fraud scoring."""

    def evaluate(self, transaction: TransactionRequest) -> tuple[float, list[str]]:
        """Run all rule checks and return (capped_score, reasons)."""
        checks = [
            self._check_high_amount(transaction),
            self._check_high_risk_country(transaction),
            self._check_round_amount(transaction),
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
        """Flag suspiciously round/clean amounts (multiples of $500)."""
        if transaction.amount > 0 and transaction.amount % ROUND_AMOUNT_MODULO == 0:
            return ROUND_AMOUNT_SCORE, "round_amount"
        return 0.0, None
