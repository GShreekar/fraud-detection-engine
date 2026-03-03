import uuid
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
    device_id: str = Field(
        default_factory=lambda: f"dev_{uuid.uuid4().hex[:12]}",
        description="Device fingerprint used for the transaction",
    )
    ip_address: str = Field(
        default_factory=lambda: f"10.{hash(uuid.uuid4()) % 256}.{hash(uuid.uuid4()) % 256}.{hash(uuid.uuid4()) % 256}",
        description="IP address of the request origin",
    )
    country: str = Field(..., min_length=2, max_length=2, description="ISO 3166-1 alpha-2 country code")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    currency: str | None = Field(default=None, description="ISO 4217 currency code")
    is_international: bool | None = Field(default=None, description="Whether the transaction crosses borders")
    customer_age: int | None = Field(default=None, description="Age of the customer in years")
    account_age_days: int | None = Field(default=None, description="Age of user account in days")
    transaction_hour: int | None = Field(default=None, description="Hour of day (0-23) the transaction occurred")
    merchant_category: str | None = Field(default=None, description="Merchant category code")
    payment_method: str | None = Field(default=None, description="Payment method used")

    model_config = {
        "json_schema_extra": {
            "example": {
                "transaction_id": "txn_001",
                "user_id": "user_42",
                "amount": 250.00,
                "merchant_id": "merchant_7",
                "device_id": "device_abc123",
                "ip_address": "192.168.1.10",
                "country": "US",
                "timestamp": "2026-02-27T10:00:00Z",
                "account_age_days": 30,
                "merchant_category": "electronics",
                "payment_method": "credit_card",
            }
        }
    }


class FraudScoreResponse(BaseModel):
    transaction_id: str
    fraud_score: float = Field(..., ge=0.0, le=1.0, description="Normalized fraud score between 0 and 1")
    decision: FraudDecision
    reasons: list[str] = Field(default_factory=list, description="Triggered rule descriptions")
