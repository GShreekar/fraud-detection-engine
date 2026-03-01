"""
FraudEngine — top-level orchestrator.

Coordinates rule checks, velocity checks, and graph checks,
then aggregates scores into a final FraudScoreResponse.
"""

from app.config import settings
from app.models.transaction import FraudDecision, FraudScoreResponse, TransactionRequest
from app.services.graph import GraphService
from app.services.rules import RulesService
from app.services.velocity import VelocityService


class FraudEngine:
    def __init__(
        self,
        rules_service: RulesService,
        velocity_service: VelocityService,
        graph_service: GraphService,
    ):
        """
        Initialize FraudEngine with service dependencies.

        Args:
            rules_service: Stateless rule-based fraud checks
            velocity_service: Redis-backed velocity checks
            graph_service: Neo4j-backed graph pattern detection
        """
        self.rules_service = rules_service
        self.velocity_service = velocity_service
        self.graph_service = graph_service

    async def evaluate(self, transaction: TransactionRequest) -> FraudScoreResponse:
        """
        Orchestrates all fraud checks and returns a scored decision.

        The final score is a weighted aggregation of:
        - Rules score (stateless checks)
        - Velocity score (Redis sliding window)
        - Graph score (Neo4j pattern detection)

        Weights are configured in Settings and must sum to 1.0.
        """
        # Collect scores from all three services
        rules_score, rules_reasons = self.rules_service.evaluate(transaction)
        velocity_score, velocity_reasons = await self.velocity_service.evaluate(
            transaction
        )
        graph_score, graph_reasons = await self.graph_service.evaluate(transaction)

        # Apply weighted aggregation
        fraud_score = (
            rules_score * settings.WEIGHT_RULES
            + velocity_score * settings.WEIGHT_VELOCITY
            + graph_score * settings.WEIGHT_GRAPH
        )

        # Ensure score does not exceed 1.0 (defensive cap)
        fraud_score = min(fraud_score, 1.0)

        # Merge all reasons from all services
        reasons: list[str] = rules_reasons + velocity_reasons + graph_reasons

        decision = self._decide(fraud_score)

        return FraudScoreResponse(
            transaction_id=transaction.transaction_id,
            fraud_score=fraud_score,
            decision=decision,
            reasons=reasons,
        )

    @staticmethod
    def _decide(score: float) -> FraudDecision:
        """
        Map fraud score to decision.

        Thresholds:
        - ALLOW  : score < 0.4
        - REVIEW : 0.4 <= score < 0.75
        - BLOCK  : score >= 0.75
        """
        if score >= 0.75:
            return FraudDecision.BLOCK
        if score >= 0.4:
            return FraudDecision.REVIEW
        return FraudDecision.ALLOW
