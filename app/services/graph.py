"""
GraphService — Neo4j-backed relationship fraud detection.

Detects shared device/IP fraud patterns, merchant fraud rings, and
new-device account takeover signals by querying the transaction
graph for suspicious connections between users, devices, IPs, and merchants.
"""

import asyncio
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

# --- Score contributions per graph pattern (merchant ring tiers) ---
MERCHANT_RING_SCORE_TIER_LOW = 0.30
MERCHANT_RING_SCORE_TIER_MID = 0.60
MERCHANT_RING_SCORE_TIER_HIGH = 0.85

# --- Score for new-device-for-user (account takeover signal) ---
NEW_DEVICE_FOR_USER_SCORE = 0.35


async def initialize_schema() -> None:
    """Create Neo4j uniqueness constraints and property indexes at startup.

    Constraints ensure MERGE operations can use index lookups instead of
    full label scans, and prevent duplicate nodes from race conditions.
    """
    driver = get_driver()
    if driver is None:
        logger.warning("neo4j_schema_init_skipped_no_driver")
        return

    constraints = [
        "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE",
        "CREATE CONSTRAINT device_id_unique IF NOT EXISTS FOR (d:Device) REQUIRE d.device_id IS UNIQUE",
        "CREATE CONSTRAINT ip_address_unique IF NOT EXISTS FOR (ip:IPAddress) REQUIRE ip.ip_address IS UNIQUE",
        "CREATE CONSTRAINT transaction_id_unique IF NOT EXISTS FOR (t:Transaction) REQUIRE t.transaction_id IS UNIQUE",
        "CREATE CONSTRAINT merchant_id_unique IF NOT EXISTS FOR (m:Merchant) REQUIRE m.merchant_id IS UNIQUE",
    ]
    indexes = [
        "CREATE INDEX device_id_index IF NOT EXISTS FOR (d:Device) ON (d.device_id)",
        "CREATE INDEX ip_address_index IF NOT EXISTS FOR (ip:IPAddress) ON (ip.ip_address)",
        "CREATE INDEX merchant_id_index IF NOT EXISTS FOR (m:Merchant) ON (m.merchant_id)",
    ]

    try:
        async with driver.session(database=settings.NEO4J_DATABASE) as session:
            for stmt in constraints + indexes:
                result = await session.run(stmt)
                await result.consume()
        logger.info("neo4j_schema_initialized")
    except Exception as exc:
        logger.warning(
            "neo4j_schema_init_failed",
            extra={"error": str(exc)},
        )


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

            async with driver.session(database=settings.NEO4J_DATABASE) as session:
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
        """MERGE nodes and relationships for the transaction, including Merchant."""
        query = """
        MERGE (u:User {user_id: $user_id})
        MERGE (d:Device {device_id: $device_id})
        MERGE (ip:IPAddress {ip_address: $ip_address})
        MERGE (m:Merchant {merchant_id: $merchant_id})
        MERGE (t:Transaction {transaction_id: $transaction_id})
          ON CREATE SET t.amount = $amount,
                        t.country = $country,
                        t.timestamp = datetime($timestamp)
        MERGE (u)-[:PERFORMED]->(t)
        MERGE (t)-[:USED_DEVICE]->(d)
        MERGE (t)-[:ORIGINATED_FROM]->(ip)
        MERGE (t)-[:AT_MERCHANT]->(m)
        """
        result = await session.run(
            query,
            user_id=transaction.user_id,
            device_id=transaction.device_id,
            ip_address=transaction.ip_address,
            merchant_id=transaction.merchant_id,
            transaction_id=transaction.transaction_id,
            amount=transaction.amount,
            country=transaction.country,
            timestamp=transaction.timestamp.isoformat(),
        )
        await result.consume()

    async def _query_patterns(
        self, session, transaction: TransactionRequest
    ) -> tuple[float, list[str]]:
        """Run all fraud pattern queries concurrently and return aggregated results."""
        checks = await asyncio.gather(
            self._check_shared_device(session, transaction),
            self._check_ip_cluster(session, transaction),
            self._check_merchant_ring(session, transaction),
            self._check_new_device_for_user(session, transaction),
        )

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
        """Count distinct users who have used this device within the time window."""
        query = """
        MATCH (u:User)-[:PERFORMED]->(t:Transaction)-[:USED_DEVICE]->(d:Device {device_id: $device_id})
        WHERE t.timestamp > datetime() - duration({days: $window_days})
        RETURN count(DISTINCT u) AS user_count
        """
        result = await session.run(
            query,
            device_id=transaction.device_id,
            window_days=settings.GRAPH_TIME_WINDOW_DAYS,
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
        """Count distinct users who have transacted from this IP within the time window."""
        query = """
        MATCH (u:User)-[:PERFORMED]->(t:Transaction)-[:ORIGINATED_FROM]->(ip:IPAddress {ip_address: $ip_address})
        WHERE t.timestamp > datetime() - duration({days: $window_days})
        RETURN count(DISTINCT u) AS user_count
        """
        result = await session.run(
            query,
            ip_address=transaction.ip_address,
            window_days=settings.GRAPH_TIME_WINDOW_DAYS,
        )
        record = await result.single()
        user_count = record["user_count"] if record else 0

        score = self._score_ip_cluster(user_count)
        if score > 0.0:
            return score, "ip_cluster"
        return 0.0, None

    async def _check_merchant_ring(
        self, session, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Count distinct users who transacted at this merchant within a window."""
        query = """
        MATCH (u:User)-[:PERFORMED]->(t:Transaction)-[:AT_MERCHANT]->(m:Merchant {merchant_id: $merchant_id})
        WHERE t.timestamp > datetime() - duration({hours: $window_hours})
        RETURN count(DISTINCT u) AS user_count
        """
        result = await session.run(
            query,
            merchant_id=transaction.merchant_id,
            window_hours=settings.GRAPH_MERCHANT_RING_WINDOW_HOURS,
        )
        record = await result.single()
        user_count = record["user_count"] if record else 0

        score = self._score_merchant_ring(user_count)
        if score > 0.0:
            return score, "merchant_fraud_ring"
        return 0.0, None

    async def _check_new_device_for_user(
        self, session, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Check if the user has ever used this device before — account takeover signal."""
        # Only score established accounts (new accounts legitimately use new devices)
        if (
            transaction.account_age_days is not None
            and transaction.account_age_days <= settings.RULE_NEW_ACCOUNT_DAYS
        ):
            return 0.0, None

        query = """
        MATCH (u:User {user_id: $user_id})-[:PERFORMED]->(:Transaction)-[:USED_DEVICE]->(d:Device {device_id: $device_id})
        RETURN count(*) AS prior_uses
        """
        result = await session.run(
            query,
            user_id=transaction.user_id,
            device_id=transaction.device_id,
        )
        record = await result.single()
        prior_uses = record["prior_uses"] if record else 0

        # prior_uses includes the transaction we just wrote; if it's the first time
        # the count will be exactly 1 (only the current transaction)
        if prior_uses <= 1:
            return NEW_DEVICE_FOR_USER_SCORE, "new_device_for_user"
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

    @staticmethod
    def _score_merchant_ring(user_count: int) -> float:
        """Map distinct user count on a merchant to a score."""
        if user_count < settings.GRAPH_MERCHANT_RING_THRESHOLD:
            return 0.0
        if user_count <= 8:
            return MERCHANT_RING_SCORE_TIER_LOW
        if user_count <= 15:
            return MERCHANT_RING_SCORE_TIER_MID
        return MERCHANT_RING_SCORE_TIER_HIGH
