"""
FraudEngine — top-level orchestrator.

Coordinates rule checks, velocity checks, and graph checks,
then aggregates scores into a final FraudScoreResponse.
"""

import logging

from app.config import settings
from app.models.transaction import FraudDecision, FraudScoreResponse, TransactionRequest

logger = logging.getLogger(__name__)
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
        When a service returns (0.0, []), its weight is redistributed
        proportionally to services that produced a non-zero score.
        """
        # Collect scores from all three services
        rules_score, rules_reasons = self.rules_service.evaluate(transaction)
        velocity_score, velocity_reasons = await self.velocity_service.evaluate(
            transaction
        )
        graph_score, graph_reasons = await self.graph_service.evaluate(transaction)

        # Adaptive weighted aggregation — redistribute inactive weight
        fraud_score = self._aggregate(
            rules_score, velocity_score, graph_score,
        )

        # Ensure score does not exceed 1.0 (defensive cap)
        fraud_score = min(fraud_score, 1.0)

        # Merge all reasons from all services
        reasons: list[str] = rules_reasons + velocity_reasons + graph_reasons

        decision = self._decide(fraud_score)

        logger.info(
            "transaction_scored",
            extra={
                "transaction_id": transaction.transaction_id,
                "fraud_score": round(fraud_score, 4),
                "decision": decision.value,
                "reasons": reasons,
            },
        )

        return FraudScoreResponse(
            transaction_id=transaction.transaction_id,
            fraud_score=fraud_score,
            decision=decision,
            reasons=reasons,
        )

    @staticmethod
    def _aggregate(
        rules_score: float,
        velocity_score: float,
        graph_score: float,
    ) -> float:
        """Compute weighted score using the standard weighted formula.

        Formula:
            final_score = min(
                rules_score  * WEIGHT_RULES +
                velocity_score * WEIGHT_VELOCITY +
                graph_score  * WEIGHT_GRAPH,
                1.0
            )

        When a service is inactive (returns 0.0), its configured weight is
        redistributed proportionally to the active services so that the
        final score is not penalised by services being unavailable.
        """
        service_weights: list[tuple[float, float]] = [
            (rules_score, settings.WEIGHT_RULES),
            (velocity_score, settings.WEIGHT_VELOCITY),
            (graph_score, settings.WEIGHT_GRAPH),
        ]

        active_weight = sum(w for s, w in service_weights if s > 0.0)

        if active_weight == 0.0:
            return 0.0

        # Weighted sum with redistribution: each active service gets
        # weight / active_weight so the active weights sum to 1.0.
        return min(
            sum(
                score * (weight / active_weight)
                for score, weight in service_weights
                if score > 0.0
            ),
            1.0,
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
