from fastapi import APIRouter, Depends

from app.models.transaction import FraudScoreResponse, TransactionRequest
from app.services.fraud_engine import FraudEngine
from app.services.graph import GraphService
from app.services.rules import RulesService
from app.services.velocity import VelocityService

router = APIRouter()


def get_fraud_engine() -> FraudEngine:
    """
    Dependency injection factory for FraudEngine.

    Instantiates all three fraud detection services and wires them
    into the FraudEngine orchestrator. This pattern enables:
    - Clean testability (services can be mocked)
    - Separation of concerns
    - Explicit dependency declaration
    """
    rules_service = RulesService()
    velocity_service = VelocityService()
    graph_service = GraphService()

    return FraudEngine(
        rules_service=rules_service,
        velocity_service=velocity_service,
        graph_service=graph_service,
    )


@router.post("/transactions/analyze", response_model=FraudScoreResponse)
async def analyze_transaction(
    transaction: TransactionRequest,
    fraud_engine: FraudEngine = Depends(get_fraud_engine),
) -> FraudScoreResponse:
    """
    Accepts a transaction payload and returns a fraud score and decision.

    Decision logic (applied in FraudEngine):
    - ALLOW  : score < 0.4
    - REVIEW : 0.4 <= score < 0.75
    - BLOCK  : score >= 0.75
    """
    result = await fraud_engine.evaluate(transaction)
    return result
