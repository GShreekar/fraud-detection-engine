"""
GraphService — Neo4j-backed relationship fraud detection.

Detects shared device/IP fraud patterns by querying the transaction
graph for suspicious connections between users, devices, and IPs.
"""

import logging

from app.config import settings
from app.db.neo4j_client import get_driver
from app.models.transaction import TransactionRequest

logger = logging.getLogger(__name__)

# --- Score contributions per graph pattern (shared device tiers) ---
SHARED_DEVICE_SCORE_TIER_LOW = 0.30
SHARED_DEVICE_SCORE_TIER_MID = 0.65
SHARED_DEVICE_SCORE_TIER_HIGH = 0.85
SHARED_DEVICE_SCORE_TIER_MAX = 1.0

# --- Score contributions per graph pattern (IP cluster tiers) ---
IP_CLUSTER_SCORE_TIER_LOW = 0.30
IP_CLUSTER_SCORE_TIER_MID = 0.60
IP_CLUSTER_SCORE_TIER_MAX = 0.90


class GraphService:
    """Async, Neo4j-backed relationship fraud pattern detection."""

    async def evaluate(
        self, transaction: TransactionRequest
    ) -> tuple[float, list[str]]:
        """Write transaction to graph and query for fraud patterns."""
        try:
            driver = get_driver()
            if driver is None:
                logger.warning(
                    "graph_neo4j_unavailable",
                    extra={
                        "transaction_id": transaction.transaction_id,
                    },
                )
                return 0.0, []

            async with driver.session() as session:
                await self._write_transaction(session, transaction)
                return await self._query_patterns(
                    session, transaction
                )
        except Exception as exc:
            logger.warning(
                "graph_check_failed",
                extra={
                    "transaction_id": transaction.transaction_id,
                    "error": str(exc),
                },
            )
            return 0.0, []

    async def _write_transaction(
        self, session, transaction: TransactionRequest
    ) -> None:
        """MERGE nodes and relationships for the transaction."""
        query = """
        MERGE (u:User {user_id: $user_id})
        MERGE (d:Device {device_id: $device_id})
        MERGE (ip:IPAddress {ip_address: $ip_address})
        MERGE (t:Transaction {transaction_id: $transaction_id})
          ON CREATE SET t.amount = $amount,
                        t.country = $country,
                        t.timestamp = $timestamp
        MERGE (u)-[:PERFORMED]->(t)
        MERGE (t)-[:USED_DEVICE]->(d)
        MERGE (t)-[:ORIGINATED_FROM]->(ip)
        """
        result = await session.run(
            query,
            user_id=transaction.user_id,
            device_id=transaction.device_id,
            ip_address=transaction.ip_address,
            transaction_id=transaction.transaction_id,
            amount=transaction.amount,
            country=transaction.country,
            timestamp=transaction.timestamp.isoformat(),
        )
        await result.consume()

    async def _query_patterns(
        self, session, transaction: TransactionRequest
    ) -> tuple[float, list[str]]:
        """Run all fraud pattern queries and return aggregated results."""
        checks = [
            await self._check_shared_device(session, transaction),
            await self._check_ip_cluster(session, transaction),
        ]

        total_score = 0.0
        reasons: list[str] = []

        for score, reason in checks:
            total_score += score
            if reason is not None:
                reasons.append(reason)

        return min(total_score, 1.0), reasons

    async def _check_shared_device(
        self, session, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Count distinct users who have used this device."""
        query = """
        MATCH (u:User)-[:PERFORMED]->
              (:Transaction)-[:USED_DEVICE]->
              (d:Device {device_id: $device_id})
        RETURN count(DISTINCT u) AS user_count
        """
        result = await session.run(
            query, device_id=transaction.device_id
        )
        record = await result.single()
        user_count = record["user_count"] if record else 0

        score = self._score_shared_device(user_count)
        if score > 0.0:
            return score, "shared_device_ring"
        return 0.0, None

    async def _check_ip_cluster(
        self, session, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Count distinct users who have transacted from this IP."""
        query = """
        MATCH (u:User)-[:PERFORMED]->
              (:Transaction)-[:ORIGINATED_FROM]->
              (ip:IPAddress {ip_address: $ip_address})
        RETURN count(DISTINCT u) AS user_count
        """
        result = await session.run(
            query, ip_address=transaction.ip_address
        )
        record = await result.single()
        user_count = record["user_count"] if record else 0

        score = self._score_ip_cluster(user_count)
        if score > 0.0:
            return score, "ip_cluster"
        return 0.0, None

    @staticmethod
    def _score_shared_device(user_count: int) -> float:
        """Map distinct user count on a device to a score."""
        if user_count < settings.GRAPH_SHARED_DEVICE_THRESHOLD:
            return 0.0
        if user_count <= 3:
            return SHARED_DEVICE_SCORE_TIER_LOW
        if user_count <= 6:
            return SHARED_DEVICE_SCORE_TIER_MID
        if user_count <= 10:
            return SHARED_DEVICE_SCORE_TIER_HIGH
        return SHARED_DEVICE_SCORE_TIER_MAX

    @staticmethod
    def _score_ip_cluster(user_count: int) -> float:
        """Map distinct user count on an IP to a score."""
        if user_count < settings.GRAPH_IP_CLUSTER_THRESHOLD:
            return 0.0
        if user_count <= 5:
            return IP_CLUSTER_SCORE_TIER_LOW
        if user_count <= 10:
            return IP_CLUSTER_SCORE_TIER_MID
        return IP_CLUSTER_SCORE_TIER_MAX
