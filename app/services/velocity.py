"""
VelocityService — Redis-backed sliding window transaction frequency checks.

Detects abnormal transaction bursts for a given user within a time window.

TODO: implement sliding window logic using Redis sorted sets.
"""

from app.models.transaction import TransactionRequest


class VelocityService:
    def __init__(self):
        # TODO: inject Redis client from app.db.redis_client
        pass

    async def evaluate(self, transaction: TransactionRequest) -> tuple[float, list[str]]:
        """
        Checks transaction velocity for the user and returns (score_contribution, reasons).
        Stub: returns (0.0, []) until Redis client is wired.
        """
        score = 0.0
        reasons: list[str] = []

        # TODO: use Redis ZADD / ZCOUNT with a sliding window key per user_id

        return score, reasons
