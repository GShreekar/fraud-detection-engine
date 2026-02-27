from fastapi import APIRouter

from app.models.transaction import FraudScoreResponse, TransactionRequest
from app.services.fraud_engine import FraudEngine

router = APIRouter()
fraud_engine = FraudEngine()


@router.post("/transactions/analyze", response_model=FraudScoreResponse)
async def analyze_transaction(transaction: TransactionRequest) -> FraudScoreResponse:
    """
    Accepts a transaction payload and returns a fraud score and decision.

    Decision logic (applied in FraudEngine):
    - ALLOW  : score < 0.4
    - REVIEW : 0.4 <= score < 0.75
    - BLOCK  : score >= 0.75
    """
    result = await fraud_engine.evaluate(transaction)
    return result
