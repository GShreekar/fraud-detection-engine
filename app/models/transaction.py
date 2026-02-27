from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FraudDecision(str, Enum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class TransactionRequest(BaseModel):
    transaction_id: str = Field(..., description="Unique transaction identifier")
    user_id: str = Field(..., description="User performing the transaction")
    amount: float = Field(..., gt=0, description="Transaction amount in USD")
    merchant_id: str = Field(..., description="Target merchant identifier")
    device_id: str = Field(..., description="Device fingerprint used for the transaction")
    ip_address: str = Field(..., description="IP address of the request origin")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "json_schema_extra": {
            "example": {
                "transaction_id": "txn_001",
                "user_id": "user_42",
                "amount": 250.00,
                "merchant_id": "merchant_7",
                "device_id": "device_abc123",
                "ip_address": "192.168.1.10",
                "timestamp": "2026-02-27T10:00:00Z",
            }
        }
    }


class FraudScoreResponse(BaseModel):
    transaction_id: str
    fraud_score: float = Field(..., ge=0.0, le=1.0, description="Normalized fraud score between 0 and 1")
    decision: FraudDecision
    reasons: list[str] = Field(default_factory=list, description="Triggered rule descriptions")
