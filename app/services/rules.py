"""
RulesService — stateless, synchronous rule-based fraud checks.

Each rule receives the transaction and returns a partial score contribution
plus an optional reason string.

TODO: implement individual rule methods.
"""

from app.models.transaction import TransactionRequest


class RulesService:
    def evaluate(self, transaction: TransactionRequest) -> tuple[float, list[str]]:
        """
        Runs all rule checks and returns (score_contribution, reasons).
        Stub: returns (0.0, []) until rules are implemented.
        """
        score = 0.0
        reasons: list[str] = []

        # TODO: add rule methods, e.g.:
        # score, reasons = self._check_high_amount(transaction, score, reasons)
        # score, reasons = self._check_blacklisted_merchant(transaction, score, reasons)

        return score, reasons
