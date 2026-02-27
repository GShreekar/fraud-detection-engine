"""
FraudEngine — top-level orchestrator.

Coordinates rule checks, velocity checks, and graph checks,
then aggregates scores into a final FraudScoreResponse.

TODO (next iterations):
  - Wire up RulesService
  - Wire up VelocityService
  - Wire up GraphService
"""

from app.models.transaction import FraudDecision, FraudScoreResponse, TransactionRequest


class FraudEngine:
    def __init__(self):
        # TODO: inject RulesService, VelocityService, GraphService
        pass

    async def evaluate(self, transaction: TransactionRequest) -> FraudScoreResponse:
        """
        Orchestrates all fraud checks and returns a scored decision.
        Stub: always returns ALLOW with score 0.0 until services are wired.
        """
        # TODO: aggregate scores from each service
        fraud_score = 0.0
        reasons: list[str] = []

        decision = self._decide(fraud_score)

        return FraudScoreResponse(
            transaction_id=transaction.transaction_id,
            fraud_score=fraud_score,
            decision=decision,
            reasons=reasons,
        )

    @staticmethod
    def _decide(score: float) -> FraudDecision:
        if score >= 0.75:
            return FraudDecision.BLOCK
        if score >= 0.4:
            return FraudDecision.REVIEW
        return FraudDecision.ALLOW
